// NeonPhantom XR — local desktop studio HTTP and WebSocket server.
// API contract: API.md in the application root.
// State lives in state.json next to the binary's data dir; no database.

use axum::{
    extract::{Path as UrlPath, Query, State as AxState, WebSocketUpgrade},
    http::StatusCode,
    response::{IntoResponse, Json},
    routing::{delete, get, post},
    Router,
};
use rand::seq::SliceRandom;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::process::Command;
use tokio::sync::{broadcast, mpsc, Mutex};

fn root() -> PathBuf {
    std::env::var_os("DESKDANCE_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            if let Ok(exe) = std::env::current_exe() {
                if let Some(directory) = exe
                    .ancestors()
                    .find(|p| p.join("video_pipeline.py").is_file())
                {
                    return directory.to_path_buf();
                }
            }
            std::env::current_dir().expect("Cannot locate application root; set DESKDANCE_ROOT")
        })
}
fn media_dir() -> PathBuf {
    std::env::var_os("DESKDANCE_MEDIA_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| root().join("samples"))
}
fn ipc_path() -> PathBuf {
    let directory = std::env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .map(|p| p.join("neonphantom-xr"))
        .unwrap_or_else(|| root().join(".runtime"));
    std::fs::create_dir_all(&directory).expect("Cannot create private player directory");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))
            .expect("Cannot protect player directory");
    }
    directory.join("player.sock")
}
fn port() -> u16 {
    std::env::var("DESKDANCE_PORT")
        .ok()
        .map(|p| p.parse().expect("DESKDANCE_PORT must be a valid port"))
        .unwrap_or(8321)
}

// ---------- state types ----------

#[derive(Serialize, Deserialize, Clone, Debug)]
struct Card {
    #[serde(default = "default_projection")]
    projection: String,
    id: String,
    file: String,
    thumb: String,
    duration_s: f64,
    has_alpha: bool,
    matted: bool,
    #[serde(default)]
    name: String,
    #[serde(default = "default_available")]
    available: bool,
    #[serde(default)]
    model: String,
    #[serde(default)]
    preview: bool,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct Job {
    #[serde(default = "default_projection")]
    projection: String,
    #[serde(default)]
    prepare_stereo: bool,
    #[serde(default = "default_stereo_device")]
    stereo_device: String,
    #[serde(default)]
    install: bool,
    #[serde(default = "default_model")]
    model: String,
    #[serde(default = "default_subject")]
    subject: String,
    #[serde(default)]
    subject_box: Option<[f64; 4]>,
    #[serde(default)]
    preview_seconds: Option<u32>,
    job_id: String,
    state: String, // queued|running|done|error
    progress: f64,
    input: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    card_id: Option<String>,
    #[serde(default = "default_mode")]
    mode: String,
    #[serde(default = "default_quality")]
    quality: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    uploaded: bool,
    #[serde(default)]
    phase: String,
    #[serde(default)]
    error: Option<String>,
    #[serde(default)]
    init_path: Option<String>,
    #[serde(default)]
    segments: Vec<String>,
}

#[derive(Serialize, Deserialize, Debug)]
struct Store {
    cards: Vec<Card>,
    playlists: HashMap<String, Vec<String>>, // name -> card ids
    jobs: Vec<Job>,
    #[serde(default)]
    favorites: Vec<String>, // favorited card ids
    #[serde(default = "default_height")]
    overlay_height: u32,
    #[serde(default = "default_corner")]
    overlay_corner: String,
}

impl Default for Store {
    fn default() -> Self {
        Self {
            cards: Vec::new(),
            playlists: HashMap::new(),
            jobs: Vec::new(),
            favorites: Vec::new(),
            overlay_height: 480,
            overlay_corner: "br".into(),
        }
    }
}

#[derive(Clone)]
struct AppState {
    store: Arc<Mutex<Store>>,
    tx: broadcast::Sender<serde_json::Value>,
    job_tx: mpsc::UnboundedSender<String>, // job_id enqueue channel (GPU-serial)
    stage: Arc<Mutex<StageState>>,
    stage_control: Arc<Mutex<()>>,
    shuffle_gen: std::sync::Arc<std::sync::atomic::AtomicUsize>, // bumped by stop/new-shuffle to cancel running sequence
}

#[derive(Debug, Serialize)]
struct StageState {
    mpv_pid: Option<u32>, // real mpv process pid (not the launcher script)
    ipc_ok: bool,         // live mpv IPC socket usable
    card_id: Option<String>,
    height_px: u32,
    corner: String,
}

impl Default for StageState {
    fn default() -> Self {
        Self {
            mpv_pid: None,
            ipc_ok: false,
            card_id: None,
            height_px: 480,
            corner: "br".into(),
        }
    }
}
fn default_available() -> bool {
    true
}
fn default_height() -> u32 {
    480
}
fn default_corner() -> String {
    "br".into()
}
fn default_mode() -> String {
    "auto".into()
}
fn default_quality() -> String {
    "detailed".into()
}
fn default_model() -> String {
    "legacy".into()
}
fn default_subject() -> String {
    "person".into()
}
fn valid_model(model: &str) -> bool {
    ["legacy", "matanyone2", "wevisone-2b", "wevisone-4b"].contains(&model)
}
fn valid_model_options(
    model: &str,
    subject: &str,
    subject_box: Option<[f64; 4]>,
    preview: Option<u32>,
) -> bool {
    valid_model(model)
        && !subject.trim().is_empty()
        && subject.chars().count() <= 200
        && preview.map(|n| (1..=10).contains(&n)).unwrap_or(true)
        && subject_box
            .map(|b| {
                b.iter().all(|n| n.is_finite() && (0.0..=1.0).contains(n))
                    && b[0] < b[2]
                    && b[1] < b[3]
            })
            .unwrap_or(true)
}
fn base_python() -> PathBuf {
    if let Some(p) = std::env::var_os("DESKDANCE_PYTHON") {
        return p.into();
    }
    #[cfg(windows)]
    {
        return root().join(".venv-ai/Scripts/python.exe");
    }
    #[cfg(not(windows))]
    {
        if root().join(".venv-cuda/.ready").is_file() {
            return root().join("gpu-python.sh");
        }
        let p = root().join(".venv-gpu/bin/python");
        if p.is_file() {
            p
        } else {
            "python3".into()
        }
    }
}
fn valid_quality(quality: &str) -> bool {
    ["detailed", "fast"].contains(&quality)
}
fn valid_mode(mode: &str) -> bool {
    ["auto", "ai", "green", "blue", "alpha", "keep"].contains(&mode)
}

fn state_path() -> PathBuf {
    std::env::var_os("DESKDANCE_STATE")
        .map(PathBuf::from)
        .unwrap_or_else(|| root().join("deskdanced/state.json"))
}

async fn save(store: &Arc<Mutex<Store>>) {
    let s = store.lock().await;
    let j = serde_json::to_string_pretty(&*s).unwrap();
    let path = state_path();
    let temp = path.with_extension("json.tmp");
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    if let Err(e) = std::fs::write(&temp, j).and_then(|_| replace_state(&temp, &path)) {
        eprintln!("Could not save library: {e}");
    }
}

fn replace_state(temp: &Path, path: &Path) -> std::io::Result<()> {
    #[cfg(not(windows))]
    {
        std::fs::rename(temp, path)
    }
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "kernel32")]
        extern "system" {
            fn MoveFileExW(existing: *const u16, target: *const u16, flags: u32) -> i32;
        }
        let source: Vec<u16> = temp.as_os_str().encode_wide().chain(Some(0)).collect();
        let target: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        // Replace atomically, without a missing-state interval during startup.
        if unsafe { MoveFileExW(source.as_ptr(), target.as_ptr(), 0x1 | 0x8) } == 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(())
    }
}

// ---------- main ----------

#[tokio::main]
async fn main() {
    let (tx, _) = broadcast::channel(256);
    let (job_tx, job_rx) = mpsc::unbounded_channel::<String>();

    // A corrupt state must never be silently replaced with an empty library.
    let loaded = match std::fs::read_to_string(state_path()) {
        Ok(json) => serde_json::from_str::<Store>(&json)
            .expect("Cannot parse library state; restore a backup instead of overwriting it"),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Store::default(),
        Err(error) => panic!("Cannot read library state: {error}"),
    };
    let store = Arc::new(Mutex::new(loaded));

    std::fs::create_dir_all(media_dir()).expect("Cannot create media directory");
    {
        let mut s = store.lock().await;
        for j in &mut s.jobs {
            if j.state == "running" || j.state == "queued" {
                j.state = "error".into();
                j.error =
                    Some("Import interrupted by restart. Please import the video again.".into());
            }
        }
    }
    save(&store).await;
    let initial_stage = {
        let s = store.lock().await;
        StageState {
            height_px: s.overlay_height.max(160).min(1600),
            corner: s.overlay_corner.clone(),
            ..StageState::default()
        }
    };
    let state = AppState {
        store,
        tx,
        job_tx,
        stage: Arc::new(Mutex::new(initial_stage)),
        stage_control: Arc::new(Mutex::new(())),
        shuffle_gen: std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0)),
    };

    // background single job queue (matting is GPU-serial)
    let qstate = state.clone();
    tokio::spawn(async move {
        let mut rx = job_rx;
        while let Some(job_id) = rx.recv().await {
            run_job(&qstate, &job_id).await;
        }
    });

    let app = Router::new()
        .route("/api/library", get(get_library))
        .route("/api/import", post(post_import))
        .route("/api/upload", post(post_upload))
        .route("/api/playlists", get(get_playlists).post(post_playlist))
        .route("/api/playlists/:name/add", post(playlist_add))
        .route("/api/playlists/:name", delete(delete_playlist))
        .route("/api/stage", get(get_stage))
        .route("/api/health", get(health))
        .route("/api/models", get(get_models))
        .route("/api/models/:id/install", post(install_model))
        .route("/api/stage/play", post(stage_play))
        .route("/api/stage/stop", post(stage_stop))
        .route("/api/stage/shuffle", post(stage_shuffle))
        .route("/api/stage/geometry", post(stage_geometry))
        .route("/api/jobs", get(get_jobs))
        .route("/api/jobs/:id/retry", post(retry_job))
        .route("/api/jobs/:id", delete(delete_job))
        .route("/api/favorites", get(get_favorites).post(post_favorite))
        .route("/api/cards/:id", delete(delete_card))
        .route("/ws", get(ws_handler))
        .nest_service("/media", tower_http::services::ServeDir::new(media_dir()))
        .fallback_service(
            tower_http::services::ServeDir::new(root().join("frontend/build")).not_found_service(
                tower_http::services::ServeFile::new(root().join("frontend/build/index.html")),
            ),
        )
        .layer(axum::middleware::from_fn(check_origin))
        .layer(axum::extract::DefaultBodyLimit::max(2 * 1024 * 1024 * 1024)) // 2 GiB for uploads (default 2 MiB breaks big files)
        .with_state(state.clone());

    // backfill: generate any missing card thumbnails (e.g. cards registered before this feature)
    {
        let bstate = state.clone();
        tokio::spawn(async move {
            let work = media_dir();
            let thumbs: Vec<(PathBuf, PathBuf)> = {
                let s = bstate.store.lock().await;
                s.cards
                    .iter()
                    .filter_map(|c| {
                        c.thumb
                            .strip_prefix("/media/")
                            .map(|t| (work.join(&c.file), work.join(t)))
                    })
                    .collect()
            };
            for (src, dst) in thumbs {
                if Path::new(&dst).exists() || !src.exists() {
                    continue;
                }
                let _ = Command::new("ffmpeg")
                    .arg("-y")
                    .arg("-c:v")
                    .arg("libvpx-vp9")
                    .arg("-i")
                    .arg(&src)
                    .args(["-frames:v", "1"])
                    .arg(Path::new(&dst))
                    .output()
                    .await;
            }
        });
    }

    let addr = format!("127.0.0.1:{}", port());
    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    println!("NeonPhantom XR studio listening on http://{addr}");
    let shutdown_state = state.clone();
    axum::serve(listener, app)
        .with_graceful_shutdown(async move {
            let _ = tokio::signal::ctrl_c().await;
            let _ = shutdown_state
                .tx
                .send(serde_json::json!({"type":"server_shutdown"}));
            shutdown_state
                .shuffle_gen
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            let _control = shutdown_state.stage_control.lock().await;
            stop_our_child(&shutdown_state).await;
        })
        .await
        .unwrap();
}

// Prevent another website from issuing uploads/player commands against the local studio.
async fn check_origin(
    request: axum::extract::Request,
    next: axum::middleware::Next,
) -> axum::response::Response {
    // Loopback binding alone does not prevent DNS rebinding: a hostile domain
    // can resolve to 127.0.0.1 and send requests with its own Host header.
    let hosts = [format!("127.0.0.1:{}", port()), format!("localhost:{}", port())];
    let valid_host = request.headers().get("host")
        .and_then(|h| h.to_str().ok())
        .map(|h| hosts.iter().any(|allowed| h.eq_ignore_ascii_case(allowed)))
        .unwrap_or(false);
    if !valid_host || request.headers().get("sec-fetch-site")
        .map(|h| h == "cross-site").unwrap_or(false) {
        return (StatusCode::FORBIDDEN, Json(serde_json::json!({"error":"Use the local studio address"}))).into_response();
    }
    if let Some(origin) = request.headers().get("origin") {
        let allowed = [
            format!("http://127.0.0.1:{}", port()),
            format!("http://localhost:{}", port()),
            "http://127.0.0.1:5173".into(),
            "http://localhost:5173".into(),
        ];
        if !origin
            .to_str()
            .map(|o| allowed.iter().any(|a| a == o))
            .unwrap_or(false)
        {
            return (
                StatusCode::FORBIDDEN,
                Json(
                    serde_json::json!({"error":"Only the local studio can send browser requests"}),
                ),
            )
                .into_response();
        }
    }
    let mut response = next.run(request).await;
    let headers = response.headers_mut();
    headers.insert("x-content-type-options", "nosniff".parse().unwrap());
    headers.insert("x-frame-options", "DENY".parse().unwrap());
    headers.insert("referrer-policy", "no-referrer".parse().unwrap());
    headers.insert("content-security-policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; frame-ancestors 'none'; base-uri 'self'".parse().unwrap());
    response
}

// ---------- REST handlers ----------

async fn get_library(AxState(st): AxState<AppState>) -> Json<Vec<Card>> {
    let mut cards = st.store.lock().await.cards.clone();
    for card in &mut cards {
        card.available = media_dir().join(&card.file).is_file();
    }
    Json(cards)
}

// DELETE /api/cards/{id} — remove card from library + playlists + favorites, delete its files.
async fn delete_card(
    AxState(st): AxState<AppState>,
    UrlPath(id): UrlPath<String>,
) -> impl IntoResponse {
    let _control = st.stage_control.lock().await;
    // find the card first (need its file/thumb names); lock released before any save()
    let Some(card) = st
        .store
        .lock()
        .await
        .cards
        .iter()
        .find(|c| c.id == id)
        .cloned()
    else {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "unknown card_id"})),
        );
    };
    // if this card is on the live stage, take it down first
    {
        let mut stage = st.stage.lock().await;
        if stage.card_id.as_deref() == Some(id.as_str()) {
            if stage.ipc_ok {
                let _ = ipc_command(&serde_json::json!({"command":["quit"]})).await;
            } else if let Some(pid) = stage.mpv_pid {
                let _ = terminate_pid(pid).await;
            }
            stage.mpv_pid = None;
            stage.ipc_ok = false;
            stage.card_id = None;
        }
    }
    let work = media_dir();
    st.shuffle_gen
        .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    // delete webm + thumb (ignore missing files)
    let _ = std::fs::remove_file(work.join(&card.file));
    if let Some(name) = card.thumb.strip_prefix("/media/") {
        let _ = std::fs::remove_file(work.join(name));
    }
    {
        let mut s = st.store.lock().await;
        s.cards.retain(|c| c.id != id);
        for pl in s.playlists.values_mut() {
            pl.retain(|x| x != &id);
        }
        s.favorites.retain(|x| x != &id);
    }
    save(&st.store).await;
    let _ = st
        .tx
        .send(serde_json::json!({"type":"card_deleted","card_id":id}));
    let stage = st.stage.lock().await;
    let _ = st.tx.send(
        serde_json::json!({"type":"stage_state","playing":stage.ipc_ok,"card_id":stage.card_id}),
    );
    (StatusCode::OK, Json(serde_json::json!({"ok": true})))
}

async fn get_models() -> impl IntoResponse {
    match Command::new(base_python())
        .arg(root().join("model_manager.py"))
        .arg("list")
        .output()
        .await
    {
        Ok(out) if out.status.success() => {
            match serde_json::from_slice::<serde_json::Value>(&out.stdout) {
                Ok(value) => (StatusCode::OK, Json(value)),
                Err(_) => (
                    StatusCode::SERVICE_UNAVAILABLE,
                    Json(serde_json::json!({"error":"Invalid model status response"})),
                ),
            }
        }
        _ => (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({"error":"Cannot inspect models. Check Python setup."})),
        ),
    }
}
async fn install_model(
    AxState(st): AxState<AppState>,
    UrlPath(id): UrlPath<String>,
) -> impl IntoResponse {
    if !valid_model(&id) || id == "legacy" {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":"Unsupported model installation"})),
        );
    }
    if st
        .store
        .lock()
        .await
        .jobs
        .iter()
        .any(|j| j.install && ["queued", "running"].contains(&j.state.as_str()))
    {
        return (
            StatusCode::CONFLICT,
            Json(serde_json::json!({"error":"A model installation is already queued or running"})),
        );
    }
    let job_id = enqueue(
        &st,
        PathBuf::new(),
        default_mode(),
        default_quality(),
        format!("Install {id}"),
        false,
        None,
        vec![],
        id,
        default_subject(),
        None,
        None,
        true,
        false,
        default_stereo_device(),
        default_projection(),
    )
    .await;
    (StatusCode::OK, Json(serde_json::json!({"job_id":job_id})))
}

async fn health() -> Json<serde_json::Value> {
    let mut checks = serde_json::Map::new();
    for tool in ["ffmpeg", "ffprobe", "mpv"] {
        if cfg!(windows) && tool == "mpv" {
            continue;
        }
        let available = Command::new(tool)
            .arg(if tool == "mpv" {
                "--version"
            } else {
                "-version"
            })
            .output()
            .await
            .map(|o| o.status.success())
            .unwrap_or(false);
        checks.insert(tool.into(), serde_json::json!(available));
    }
    #[cfg(windows)]
    {
        checks.insert(
            "desktop_player".into(),
            serde_json::json!(Command::new(base_python())
                .args(["-c", "import PySide6"])
                .status()
                .await
                .map(|s| s.success())
                .unwrap_or(false)),
        );
    }
    Json(
        serde_json::json!({"platform": std::env::consts::OS, "tools": checks, "features":{"m4s_segments":true,"retry_imports":true,"fast_ai":true,"vr180_passthrough":true,"auto_stereo":true,"model_picker":true,"preview_imports":true}, "desktop_session": cfg!(windows) || std::env::var("WAYLAND_DISPLAY").is_ok() || std::env::var("DISPLAY").is_ok()}),
    )
}
async fn get_stage(AxState(st): AxState<AppState>) -> Json<serde_json::Value> {
    let s = st.stage.lock().await;
    Json(
        serde_json::json!({"playing":s.ipc_ok,"card_id":s.card_id,"height_px":s.height_px,"corner":s.corner}),
    )
}

#[derive(Deserialize)]
struct ImportBody {
    #[serde(default = "default_projection")]
    projection: String,
    #[serde(default)]
    prepare_stereo: bool,
    #[serde(default = "default_stereo_device")]
    stereo_device: String,
    #[serde(default = "default_model")]
    model: String,
    #[serde(default = "default_subject")]
    subject: String,
    #[serde(default)]
    subject_box: Option<[f64; 4]>,
    #[serde(default)]
    preview_seconds: Option<u32>,
    path: String,
    #[serde(default)]
    init_path: Option<String>,
    #[serde(default)]
    segments: Vec<String>,
    #[serde(default = "default_mode")]
    mode: String,
    #[serde(default = "default_quality")]
    quality: String,
}
fn default_projection() -> String { "flat".into() }
fn valid_projection(value: &str) -> bool { matches!(value, "flat" | "vr180-sbs") }
fn default_stereo_device() -> String { "auto".into() }
fn valid_stereo_device(value: &str) -> bool { matches!(value, "auto" | "gpu" | "cpu") }
async fn enqueue(
    st: &AppState,
    path: PathBuf,
    mode: String,
    quality: String,
    name: String,
    uploaded: bool,
    init_path: Option<String>,
    segments: Vec<String>,
    model: String,
    subject: String,
    subject_box: Option<[f64; 4]>,
    preview_seconds: Option<u32>,
    install: bool,
    prepare_stereo: bool,
    stereo_device: String,
    projection: String,
) -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let job_id = short_id(&format!("{}{now}", path.display()));
    st.store.lock().await.jobs.push(Job {
        job_id: job_id.clone(),
        prepare_stereo,
        stereo_device,
        projection,
        model,
        subject,
        subject_box,
        preview_seconds,
        install,
        state: "queued".into(),
        progress: 0.0,
        input: path.display().to_string(),
        card_id: None,
        mode,
        quality,
        name,
        uploaded,
        phase: "Queued".into(),
        error: None,
        init_path,
        segments,
    });
    save(&st.store).await;
    let _ = st.job_tx.send(job_id.clone());
    job_id
}
async fn post_import(
    AxState(st): AxState<AppState>,
    Json(body): Json<ImportBody>,
) -> impl IntoResponse {
    let p = PathBuf::from(&body.path);
    let extras = body.init_path.iter().chain(body.segments.iter());
    if !p.is_absolute()
        || !p.is_file()
        || !valid_mode(&body.mode)
        || !valid_quality(&body.quality)
        || !valid_stereo_device(&body.stereo_device)
        || !valid_projection(&body.projection)
        || (body.prepare_stereo && body.projection != "flat")
        || !valid_model_options(
            &body.model,
            &body.subject,
            body.subject_box,
            body.preview_seconds,
        )
        || (body.preview_seconds.is_some()
            && (body.init_path.is_some() || !body.segments.is_empty()))
        || extras
            .into_iter()
            .any(|f| !Path::new(f).is_absolute() || !Path::new(f).is_file())
    {
        return (
            StatusCode::BAD_REQUEST,
            Json(
                serde_json::json!({"error":"Use an existing absolute video path and a supported background mode."}),
            ),
        );
    }
    let name = p
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .to_string();
    let job_id = enqueue(
        &st,
        p,
        body.mode,
        body.quality,
        name,
        false,
        body.init_path,
        body.segments,
        body.model,
        body.subject,
        body.subject_box,
        body.preview_seconds,
        false,
        body.prepare_stereo,
        body.stereo_device,
        body.projection,
    )
    .await;
    (StatusCode::OK, Json(serde_json::json!({"job_id":job_id})))
}

fn query_box<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<[f64; 4]>, D::Error> {
    let value = Option::<String>::deserialize(deserializer)?;
    value
        .map(|v| serde_json::from_str(&v).map_err(serde::de::Error::custom))
        .transpose()
}
#[derive(Deserialize)]
struct UploadOptions {
    #[serde(default = "default_projection")]
    projection: String,
    #[serde(default)]
    prepare_stereo: bool,
    #[serde(default = "default_stereo_device")]
    stereo_device: String,
    #[serde(default = "default_model")]
    model: String,
    #[serde(default = "default_subject")]
    subject: String,
    #[serde(default)]
    #[serde(deserialize_with = "query_box")]
    subject_box: Option<[f64; 4]>,
    #[serde(default)]
    preview_seconds: Option<u32>,
    #[serde(default)]
    segments: bool,
    #[serde(default = "default_mode")]
    mode: String,
    #[serde(default = "default_quality")]
    quality: String,
}
async fn post_upload(
    AxState(st): AxState<AppState>,
    Query(options): Query<UploadOptions>,
    mut mp: axum::extract::Multipart,
) -> impl IntoResponse {
    use tokio::io::AsyncWriteExt;
    if !valid_mode(&options.mode)
        || !valid_quality(&options.quality)
        || !valid_stereo_device(&options.stereo_device)
        || !valid_projection(&options.projection)
        || (options.prepare_stereo && options.projection != "flat")
        || !valid_model_options(
            &options.model,
            &options.subject,
            options.subject_box,
            options.preview_seconds,
        )
        || (options.segments && options.preview_seconds.is_some())
    {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":"Unsupported background mode"})),
        );
    }
    let mut saved = Vec::<PathBuf>::new();
    let mut files = Vec::<(PathBuf, String)>::new();
    let mut init_path = None;
    let mut bytes = 0usize;
    let result: Result<(), String> = async {
        while let Some(mut field) = mp.next_field().await.map_err(|e| format!("Upload failed: {e}"))? {
            let is_init = field.name() == Some("init");
            if field.name() != Some("file") && !is_init { continue; }
            if (!options.segments && (is_init || !files.is_empty())) || (is_init && init_path.is_some()) {
                return Err("Use the M4S segment importer for an initialization file and multiple segments.".into());
            }
            if saved.len() >= 4096 { return Err("Import at most 4096 segments at a time.".into()); }
            let name = field.file_name().unwrap_or("video").rsplit(['/', '\\']).next().unwrap_or("video").to_string();
            let ext = Path::new(&name).extension().map(|e| e.to_string_lossy().to_lowercase())
                .filter(|e| e.len() <= 12 && e.chars().all(|c| c.is_ascii_alphanumeric())).unwrap_or_else(|| "bin".into());
            let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
            let path = media_dir().join(format!("upload_{now}_{}.{ext}", saved.len()));
            let mut file = tokio::fs::File::create(&path).await.map_err(|e| format!("Cannot save upload: {e}"))?;
            saved.push(path.clone());
            let before = bytes;
            while let Some(chunk) = field.chunk().await.map_err(|e| e.to_string())? {
                bytes += chunk.len();
                if bytes > 2 * 1024 * 1024 * 1024 { return Err("Combined upload exceeds 2 GiB.".into()); }
                file.write_all(&chunk).await.map_err(|e| e.to_string())?;
            }
            if bytes == before { return Err(format!("{name} is empty")); }
            file.flush().await.map_err(|e| e.to_string())?;
            if is_init { init_path = Some(path.display().to_string()); }
            else { files.push((path, name)); }
        }
        if files.is_empty() { return Err("Select at least one video segment.".into()); }
        Ok(())
    }.await;
    if let Err(error) = result {
        for path in saved {
            let _ = tokio::fs::remove_file(path).await;
        }
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":error})),
        );
    }
    let (path, first_name) = files.remove(0);
    let name = if files.is_empty() {
        first_name
    } else {
        format!("{first_name} + {} segments", files.len())
    };
    let segments = files
        .into_iter()
        .map(|(p, _)| p.display().to_string())
        .collect();
    let job_id = enqueue(
        &st,
        path,
        options.mode,
        options.quality,
        name,
        true,
        init_path,
        segments,
        options.model,
        options.subject,
        options.subject_box,
        options.preview_seconds,
        false,
        options.prepare_stereo,
        options.stereo_device,
        options.projection,
    )
    .await;
    (StatusCode::OK, Json(serde_json::json!({"job_id":job_id})))
}

async fn get_playlists(AxState(st): AxState<AppState>) -> Json<Vec<serde_json::Value>> {
    let s = st.store.lock().await;
    Json(
        s.playlists
            .iter()
            .map(|(name, cards)| serde_json::json!({"name": name, "cards": cards}))
            .collect(),
    )
}

#[derive(Deserialize)]
struct PlaylistBody {
    name: String,
}

async fn post_playlist(
    AxState(st): AxState<AppState>,
    Json(body): Json<PlaylistBody>,
) -> impl IntoResponse {
    {
        st.store
            .lock()
            .await
            .playlists
            .entry(body.name)
            .or_default();
    }
    save(&st.store).await;
    (StatusCode::OK, Json(serde_json::json!({"ok": true})))
}

#[derive(Deserialize)]
struct AddBody {
    card_id: String,
}

async fn playlist_add(
    AxState(st): AxState<AppState>,
    UrlPath(name): UrlPath<String>,
    Json(body): Json<AddBody>,
) -> impl IntoResponse {
    {
        let mut s = st.store.lock().await;
        if !s.cards.iter().any(|c| c.id == body.card_id) {
            return (
                StatusCode::NOT_FOUND,
                Json(serde_json::json!({"error": "unknown card_id"})),
            );
        }
        s.playlists.entry(name.clone()).or_default();
        if !s.playlists[&name].contains(&body.card_id) {
            s.playlists.get_mut(&name).unwrap().push(body.card_id);
        }
    }
    save(&st.store).await;
    (StatusCode::OK, Json(serde_json::json!({"ok": true})))
}

async fn delete_playlist(
    AxState(st): AxState<AppState>,
    UrlPath(name): UrlPath<String>,
) -> impl IntoResponse {
    let removed = { st.store.lock().await.playlists.remove(&name).is_some() };
    save(&st.store).await;
    if removed {
        (StatusCode::OK, Json(serde_json::json!({"ok": true})))
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error":"no such playlist"})),
        )
    }
}

#[derive(Deserialize)]
struct PlayBody {
    card_id: String,
}

async fn stage_play(
    AxState(st): AxState<AppState>,
    Json(body): Json<PlayBody>,
) -> impl IntoResponse {
    let _control = st.stage_control.lock().await;
    let card = {
        st.store
            .lock()
            .await
            .cards
            .iter()
            .find(|c| c.id == body.card_id)
            .cloned()
    };
    let card = match card {
        Some(c) => c,
        None => {
            return (
                StatusCode::NOT_FOUND,
                Json(serde_json::json!({"error":"unknown card_id"})),
            )
        }
    };
    let webm = media_dir().join(&card.file);
    st.shuffle_gen
        .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    if let Err(e) = play_card(&st, &webm).await {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({"error":e})),
        );
    }
    (StatusCode::OK, Json(serde_json::json!({"ok": true})))
}

async fn stage_stop(AxState(st): AxState<AppState>) -> impl IntoResponse {
    let _control = st.stage_control.lock().await;
    st.shuffle_gen
        .fetch_add(1, std::sync::atomic::Ordering::Relaxed); // cancel any running shuffle sequence
    let mut stage = st.stage.lock().await;
    if stage.ipc_ok {
        // mpv quit via IPC is the clean path (killing bar-dancer.sh would orphan mpv)
        let _ = ipc_command(&serde_json::json!({"command":["quit"]})).await;
    } else if let Some(pid) = stage.mpv_pid {
        // kill only OUR child (never a pre-existing mpv-dancer we didn't launch)
        let _ = terminate_pid(pid).await;
    }
    stage.mpv_pid = None;
    stage.ipc_ok = false;
    stage.card_id = None;
    drop(stage);
    let _ = st
        .tx
        .send(serde_json::json!({"type":"stage_state","playing":false,"card_id":null}));
    (StatusCode::OK, Json(serde_json::json!({"ok": true})))
}

#[derive(Deserialize)]
struct ShuffleBody {
    #[serde(default)]
    playlist: Option<String>,
    #[serde(default)]
    card_ids: Option<Vec<String>>, // explicit id list (e.g. favorites); wins over playlist
}

async fn stage_shuffle(
    AxState(st): AxState<AppState>,
    Json(body): Json<ShuffleBody>,
) -> impl IntoResponse {
    let ids: Vec<String> = {
        let s = st.store.lock().await;
        match (&body.card_ids, &body.playlist) {
            (Some(ids), _) => ids.clone(),
            (_, Some(name)) => s.playlists.get(name).cloned().unwrap_or_default(),
            _ => s.cards.iter().map(|c| c.id.clone()).collect(),
        }
    };
    if ids.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":"empty playlist"})),
        );
    }
    let mut ids = ids;
    use rand::SeedableRng;
    ids.shuffle(&mut rand::rngs::StdRng::from_entropy());

    // durations for the sequential runner (card_id -> seconds)
    let durs: Vec<(String, f64)> = {
        let s = st.store.lock().await;
        ids.iter()
            .filter_map(|id| {
                s.cards
                    .iter()
                    .find(|c| &c.id == id)
                    .map(|c| (id.clone(), c.duration_s.max(1.0)))
            })
            .collect()
    };

    if durs.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":"No playable cards in this selection"})),
        );
    }

    // cancel any previous shuffle run, spawn the new one
    let my_gen = st
        .shuffle_gen
        .fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        + 1;
    let gst = st.clone();
    tokio::spawn(async move {
        for (id, dur) in durs {
            if gst.shuffle_gen.load(std::sync::atomic::Ordering::Relaxed) != my_gen {
                return;
            } // superseded/stopped
            let webm = {
                let s = gst.store.lock().await;
                s.cards
                    .iter()
                    .find(|c| c.id == *id)
                    .map(|c| media_dir().join(&c.file))
            };
            let Some(webm) = webm else { continue };
            let control = gst.stage_control.lock().await;
            if gst.shuffle_gen.load(std::sync::atomic::Ordering::Relaxed) != my_gen {
                return;
            }
            if let Err(e) = play_card(&gst, &webm).await {
                let _ = gst
                    .tx
                    .send(serde_json::json!({"type":"stage_error","error":e}));
                return;
            }
            drop(control);
            // stay on this clip for its duration (+0.5s transition slack), wake early if cancelled
            let deadline =
                tokio::time::Instant::now() + std::time::Duration::from_secs_f64(dur + 0.5);
            loop {
                tokio::time::sleep(std::time::Duration::from_millis(250)).await;
                if gst.shuffle_gen.load(std::sync::atomic::Ordering::Relaxed) != my_gen {
                    return;
                }
                if tokio::time::Instant::now() >= deadline {
                    break;
                }
            }
        }
        // sequence finished naturally: stop the overlay
        let _control = gst.stage_control.lock().await;
        if gst.shuffle_gen.load(std::sync::atomic::Ordering::Relaxed) == my_gen {
            stop_our_child(&gst).await;
            update_stage_state(&gst, None, false).await;
        }
    });
    (
        StatusCode::OK,
        Json(serde_json::json!({"ok": true, "queued": ids.len()})),
    )
}

#[derive(Deserialize)]
struct GeometryBody {
    height_px: u32,
    corner: String,
}

async fn stage_geometry(
    AxState(st): AxState<AppState>,
    Json(body): Json<GeometryBody>,
) -> impl IntoResponse {
    let _control = st.stage_control.lock().await;
    if !(160..=1600).contains(&body.height_px)
        || !["br", "bl", "tr", "tl"].contains(&body.corner.as_str())
    {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":"Height must be 160–1600 px; choose a valid corner."})),
        );
    }
    let card_id = st.stage.lock().await.card_id.clone();
    let card_file = {
        st.store
            .lock()
            .await
            .cards
            .iter()
            .find(|c| Some(&c.id) == card_id.as_ref())
            .map(|c| c.file.clone())
    };
    {
        let mut stage = st.stage.lock().await;
        stage.height_px = body.height_px;
        stage.corner = body.corner.clone();
    }
    {
        let mut store = st.store.lock().await;
        store.overlay_height = body.height_px;
        store.overlay_corner = body.corner.clone();
    }
    save(&st.store).await;
    // relaunch/reposition: kill our child and relaunch bar-dancer.sh with new geometry
    if let Some(f) = card_file {
        let webm = media_dir().join(f);
        stop_our_child(&st).await;
        if let Err(e) = launch_overlay(&st, &webm, body.height_px, &body.corner).await {
            return (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(serde_json::json!({"error":e})),
            );
        }
    } else {
        // remember geometry for next play; nothing live to reposition
        let stage = st.stage.lock().await;
        if !stage.ipc_ok && stage.mpv_pid.is_none() {
            return (
                StatusCode::OK,
                Json(
                    serde_json::json!({"ok": true, "note": "geometry saved for next play; nothing playing"}),
                ),
            );
        }
    }
    (StatusCode::OK, Json(serde_json::json!({"ok": true})))
}

async fn get_favorites(AxState(st): AxState<AppState>) -> Json<Vec<String>> {
    Json(st.store.lock().await.favorites.clone())
}

#[derive(Deserialize)]
struct FavBody {
    card_id: String,
}

// POST /api/favorites — toggle a card's favorite state.
async fn post_favorite(
    AxState(st): AxState<AppState>,
    Json(body): Json<FavBody>,
) -> impl IntoResponse {
    let fav = {
        let mut s = st.store.lock().await;
        if !s.cards.iter().any(|c| c.id == body.card_id) {
            return (
                StatusCode::NOT_FOUND,
                Json(serde_json::json!({"error": "unknown card_id"})),
            );
        }
        if let Some(i) = s.favorites.iter().position(|x| x == &body.card_id) {
            s.favorites.remove(i);
            false
        } else {
            s.favorites.push(body.card_id.clone());
            true
        }
    };
    save(&st.store).await;
    (StatusCode::OK, Json(serde_json::json!({"favorited": fav})))
}

fn source_available(job: &Job) -> bool {
    std::iter::once(&job.input)
        .chain(job.init_path.iter())
        .chain(job.segments.iter())
        .all(|p| Path::new(p).is_file())
}
async fn get_jobs(AxState(st): AxState<AppState>) -> Json<Vec<serde_json::Value>> {
    let jobs = st.store.lock().await.jobs.clone();
    Json(
        jobs.iter()
            .map(|job| {
                let mut value = serde_json::to_value(job).unwrap();
                value["can_retry"] = serde_json::json!(
                    job.state == "error" && (job.install || source_available(job))
                );
                value
            })
            .collect(),
    )
}
#[derive(Deserialize)]
struct RetryBody {
    #[serde(default)]
    model: Option<String>,
    #[serde(default)]
    subject: Option<String>,
    #[serde(default)]
    subject_box: Option<[f64; 4]>,
    #[serde(default)]
    mode: Option<String>,
    #[serde(default)]
    quality: Option<String>,
}
async fn retry_job(
    AxState(st): AxState<AppState>,
    UrlPath(id): UrlPath<String>,
    Json(body): Json<RetryBody>,
) -> impl IntoResponse {
    {
        let mut store = st.store.lock().await;
        let Some(job) = store.jobs.iter_mut().find(|j| j.job_id == id) else {
            return (
                StatusCode::NOT_FOUND,
                Json(serde_json::json!({"error":"Import not found"})),
            );
        };
        if job.state != "error" {
            return (
                StatusCode::CONFLICT,
                Json(serde_json::json!({"error":"Only failed imports can be retried"})),
            );
        }
        if !job.install && !source_available(job) {
            return (
                StatusCode::BAD_REQUEST,
                Json(
                    serde_json::json!({"error":"Source files are unavailable. Upload the video again."}),
                ),
            );
        }
        let mode = body.mode.unwrap_or_else(|| job.mode.clone());
        let quality = body.quality.unwrap_or_else(|| job.quality.clone());
        if !valid_mode(&mode) || !valid_quality(&quality) {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({"error":"Unsupported background mode"})),
            );
        }
        let model = body.model.unwrap_or_else(|| job.model.clone());
        let subject = body.subject.unwrap_or_else(|| job.subject.clone());
        let subject_box = body.subject_box.or(job.subject_box);
        if !valid_model_options(&model, &subject, subject_box, job.preview_seconds) {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({"error":"Invalid model options"})),
            );
        }
        if !job.install {
            job.model = model;
            job.subject = subject;
            job.subject_box = subject_box;
        }
        job.mode = mode;
        job.quality = quality;
        job.state = "queued".into();
        job.progress = 0.0;
        job.phase = "Queued".into();
        job.error = None;
    }
    save(&st.store).await;
    let _ = st.job_tx.send(id.clone());
    (StatusCode::OK, Json(serde_json::json!({"job_id":id})))
}
async fn delete_job(
    AxState(st): AxState<AppState>,
    UrlPath(id): UrlPath<String>,
) -> impl IntoResponse {
    let job = {
        let mut store = st.store.lock().await;
        let Some(index) = store.jobs.iter().position(|j| j.job_id == id) else {
            return (
                StatusCode::NOT_FOUND,
                Json(serde_json::json!({"error":"Import not found"})),
            );
        };
        if ["queued", "running"].contains(&store.jobs[index].state.as_str()) {
            return (
                StatusCode::CONFLICT,
                Json(serde_json::json!({"error":"Wait for this import to finish first"})),
            );
        }
        store.jobs.remove(index)
    };
    if job.uploaded {
        for path in std::iter::once(&job.input)
            .chain(job.init_path.iter())
            .chain(job.segments.iter())
        {
            let _ = tokio::fs::remove_file(path).await;
        }
    }
    save(&st.store).await;
    let _ = st
        .tx
        .send(serde_json::json!({"type":"job_deleted","job_id":id}));
    (StatusCode::OK, Json(serde_json::json!({"ok":true})))
}

// ---------- WebSocket ----------

async fn ws_handler(ws: WebSocketUpgrade, AxState(st): AxState<AppState>) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_ws(socket, st))
}

async fn handle_ws(mut socket: axum::extract::ws::WebSocket, st: AppState) {
    let mut rx = st.tx.subscribe();
    // welcome event so clients know the stream is live
    let _ = socket
        .send(axum::extract::ws::Message::Text(
            serde_json::json!({"type":"hello"}).to_string().into(),
        ))
        .await;
    loop {
        tokio::select! {
            ev = rx.recv() => match ev {
                Ok(v) => { if v["type"] == "server_shutdown" { break; } if socket.send(axum::extract::ws::Message::Text(v.to_string().into())).await.is_err() { break; } }
                Err(broadcast::error::RecvError::Lagged(_)) => continue,
                Err(_) => break,
            },
            msg = socket.recv() => match msg {
                Some(Ok(_)) => {} // client messages ignored
                _ => break,
            }
        }
    }
}

// ---------- job pipeline (GPU-serial via the single consumer task) ----------

async fn set_job(st: &AppState, job_id: &str, state: &str, progress: f64) {
    let job = {
        let mut s = st.store.lock().await;
        s.jobs.iter_mut().find(|j| j.job_id == job_id).map(|j| {
            j.state = state.into();
            j.progress = progress;
            j.clone()
        })
    };
    save(&st.store).await;
    if let Some(job) = job {
        let _ = st.tx.send(serde_json::json!({"type":"job_progress","job_id":job_id,"progress":progress,"state":state,"phase":job.phase}));
    }
}

async fn run_job(st: &AppState, job_id: &str) {
    use tokio::io::{AsyncBufReadExt, BufReader};
    let job = st
        .store
        .lock()
        .await
        .jobs
        .iter()
        .find(|j| j.job_id == job_id)
        .cloned()
        .unwrap();
    set_job(st, job_id, "running", 0.0).await;
    let output = media_dir().join(format!("{job_id}.webm"));
    let python = base_python();
    let mut command = Command::new(python);
    command.kill_on_drop(true);
    if job.install {
        command
            .arg(root().join("model_manager.py"))
            .args(["install", &job.model]);
    } else {
        command
            .arg(root().join("video_pipeline.py"))
            .arg(&job.input)
            .arg(&output)
            .args([
                "--projection",
                &job.projection,
                "--mode",
                &job.mode,
                "--quality",
                &job.quality,
                "--model",
                &job.model,
                "--subject",
                &job.subject,
            ]);
        if let Some(b) = &job.subject_box {
            command.arg("--box").arg(serde_json::to_string(b).unwrap());
        }
        if let Some(seconds) = job.preview_seconds {
            command.arg("--preview-seconds").arg(seconds.to_string());
        }
        if let Some(init) = &job.init_path {
            command.arg("--init").arg(init);
        }
        for segment in &job.segments {
            command.arg("--segment").arg(segment);
        }
    }
    let child = command
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn();
    let mut result = None;
    let outcome: Result<(), String> = async {
        let mut child = child.map_err(|e| format!("Cannot start video converter: {e}"))?;
        let mut lines = BufReader::new(child.stdout.take().unwrap()).lines();
        let mut failure = None;
        while let Some(line) = lines.next_line().await.map_err(|e| e.to_string())? {
            if let Ok(event) = serde_json::from_str::<serde_json::Value>(&line) {
                if let Some(error) = event["error"].as_str() { failure = Some(error.to_string()); }
                if let Some(progress) = event["progress"].as_f64() {
                    let mut s = st.store.lock().await;
                    if let Some(j) = s.jobs.iter_mut().find(|j| j.job_id == job_id) {
                        j.phase = event["phase"].as_str().unwrap_or("Processing").into();
                    }
                    drop(s);
                    set_job(st, job_id, "running", progress.min(0.99)).await;
                }
                if event.get("result").is_some() { result = Some(event["result"].clone()); }
            }
        }
        let status = child.wait().await.map_err(|e| e.to_string())?;
        if !status.success() || result.is_none() { return Err(failure.unwrap_or_else(|| "Video conversion failed. Check ffmpeg, Python dependencies, and available disk space.".into())); }
        Ok(())
    }.await;
    if job.install && outcome.is_ok() {
        {
            let mut s = st.store.lock().await;
            if let Some(j) = s.jobs.iter_mut().find(|j| j.job_id == job_id) {
                j.phase = "Model installed".into();
            }
        }
        set_job(st, job_id, "done", 1.0).await;
        let _ = st.tx.send(serde_json::json!({"type":"models_changed"}));
        return;
    }
    if job.uploaded && outcome.is_ok() {
        for path in std::iter::once(&job.input)
            .chain(job.init_path.iter())
            .chain(job.segments.iter())
        {
            let _ = tokio::fs::remove_file(path).await;
        }
    }
    if let Err(e) = outcome {
        let _ = tokio::fs::remove_file(&output).await;
        let _ = tokio::fs::remove_file(media_dir().join(format!("thumb_{job_id}.png"))).await;
        job_error(st, job_id, &e).await;
        return;
    }
    let result = result.unwrap();
    {
        let mut s = st.store.lock().await;
        s.cards.push(Card {
            projection: result["projection"].as_str().unwrap_or(&job.projection).into(),
            id: job_id.into(),
            file: format!("{job_id}.webm"),
            thumb: format!("/media/thumb_{job_id}.png"),
            duration_s: result["duration_s"].as_f64().unwrap_or(0.0),
            has_alpha: result["has_alpha"].as_bool().unwrap_or(false),
            matted: result["matted"].as_bool().unwrap_or(false),
            name: if job.preview_seconds.is_some() {
                format!("Preview · {}", job.name)
            } else {
                job.name
            },
            available: true,
            model: result["model"].as_str().unwrap_or("").into(),
            preview: job.preview_seconds.is_some(),
        });
        if let Some(j) = s.jobs.iter_mut().find(|j| j.job_id == job_id) {
            j.card_id = Some(job_id.into());
            j.phase = "Ready".into();
            j.state = "done".into();
            j.progress = 1.0;
        }
    }
    save(&st.store).await;
    let _ = st
        .tx
        .send(serde_json::json!({"type":"job_done","job_id":job_id,"card_id":job_id}));
}

async fn job_error(st: &AppState, job_id: &str, msg: &str) {
    eprintln!("[job {job_id}] ERROR: {msg}");
    {
        let mut s = st.store.lock().await;
        if let Some(j) = s.jobs.iter_mut().find(|j| j.job_id == job_id) {
            j.state = "error".into();
            j.error = Some(msg.into());
        }
    }
    save(&st.store).await;
    let _ = st.tx.send(
        serde_json::json!({"type":"job_progress","job_id":job_id,"state":"error","error":msg}),
    );
}

// ---------- stage helpers ----------

async fn play_card(st: &AppState, webm: &Path) -> Result<(), String> {
    let (ipc_ok, h, corner) = {
        let s = st.stage.lock().await;
        (s.ipc_ok, s.height_px, s.corner.clone())
    };
    if ipc_ok
        && ipc_command(
            &serde_json::json!({"command":["loadfile", webm.to_string_lossy(), "replace"]}),
        )
        .await
        .is_ok()
    {
        update_stage_state(st, Some(short_id_input(webm)), true).await;
        return Ok(());
    }
    launch_overlay(st, webm, h, &corner).await
}

async fn terminate_pid(pid: u32) -> std::io::Result<std::process::ExitStatus> {
    #[cfg(windows)]
    {
        Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .status()
            .await
    }
    #[cfg(not(windows))]
    {
        Command::new("kill").arg(pid.to_string()).status().await
    }
}
async fn stop_our_child(st: &AppState) {
    let pid = st.stage.lock().await.mpv_pid;
    if let Some(pid) = pid {
        let _ = terminate_pid(pid).await;
    }
    let mut s = st.stage.lock().await;
    s.mpv_pid = None;
    s.ipc_ok = false;
    s.card_id = None;
}

async fn launch_overlay(st: &AppState, webm: &Path, h: u32, corner: &str) -> Result<(), String> {
    if !webm.is_file() {
        return Err("Video file is missing. Import it again.".into());
    }
    stop_our_child(st).await;
    let _ = tokio::fs::remove_file(ipc_path()).await;
    let log_path = ipc_path().with_extension("log");
    let log = std::fs::File::create(&log_path).map_err(|e| e.to_string())?;
    #[cfg(not(windows))]
    let mut launcher = {
        let mut c = Command::new("bash");
        c.arg(root().join("bar-dancer.sh"))
            .arg(webm)
            .arg(h.to_string())
            .arg(corner)
            .env("DESKDANCE_IPC", ipc_path());
        c
    };
    #[cfg(windows)]
    let mut launcher = {
        let mut c = Command::new(base_python());
        c.arg(root().join("windows_overlay.py"))
            .arg(webm)
            .arg(h.to_string())
            .arg(corner)
            .arg("--port")
            .arg(player_port().to_string())
            .arg("--token")
            .arg(player_token());
        c
    };
    let mut child = launcher
        .kill_on_drop(true)
        .stdout(std::process::Stdio::null())
        .stderr(log)
        .spawn()
        .map_err(|e| format!("Cannot launch desktop player: {e}"))?;
    let pid = child.id();
    for _ in 0..30 {
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            let details = tokio::fs::read_to_string(&log_path)
                .await
                .unwrap_or_default();
            return Err(format!(
                "Desktop player exited ({status}): {}",
                details.chars().take(1500).collect::<String>()
            ));
        }
        if ipc_command(&serde_json::json!({"command":["get_property","path"]}))
            .await
            .is_ok()
        {
            {
                let mut s = st.stage.lock().await;
                s.mpv_pid = pid;
                s.ipc_ok = true;
            }
            update_stage_state(st, Some(short_id_input(webm)), true).await;
            let state = st.clone();
            tokio::spawn(async move {
                let outcome = child.wait().await;
                let mut s = state.stage.lock().await;
                if s.mpv_pid == pid {
                    if !outcome.map(|status| status.success()).unwrap_or(false) {
                        let details = tokio::fs::read_to_string(&log_path)
                            .await
                            .unwrap_or_default();
                        let _ = state.tx.send(serde_json::json!({"type":"stage_error","error":format!("Desktop player stopped: {}", details.chars().take(1500).collect::<String>())}));
                    }
                    s.mpv_pid = None;
                    s.ipc_ok = false;
                    s.card_id = None;
                    let _ = state.tx.send(
                        serde_json::json!({"type":"stage_state","playing":false,"card_id":null}),
                    );
                }
            });
            return Ok(());
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
    let _ = child.kill().await;
    update_stage_state(st, None, false).await;
    Err(
        "Player did not become ready. Check mpv and launch the server from your desktop session."
            .into(),
    )
}

async fn update_stage_state(st: &AppState, card_id: Option<String>, playing: bool) {
    st.stage.lock().await.card_id = card_id.clone();
    let _ = st
        .tx
        .send(serde_json::json!({"type":"stage_state","playing":playing,"card_id":card_id}));
}

#[cfg(windows)]
fn player_port() -> u16 {
    port()
        .checked_add(1)
        .expect("DESKDANCE_PORT must be below 65535")
}
#[cfg(windows)]
fn player_token() -> &'static str {
    static TOKEN: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    TOKEN.get_or_init(|| {
        use rand::RngCore;
        let mut bytes = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut bytes);
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    })
}

async fn ipc_command(
    cmd: &serde_json::Value,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
    let action = async {
        #[cfg(not(windows))]
        let mut stream = tokio::net::UnixStream::connect(ipc_path()).await?;
        #[cfg(windows)]
        let mut stream = tokio::net::TcpStream::connect(("127.0.0.1", player_port())).await?;
        #[cfg(windows)]
        let cmd = {
            let mut c = cmd.clone();
            c["token"] = serde_json::json!(player_token());
            c
        };

        stream.write_all(format!("{}\n", cmd).as_bytes()).await?;
        let mut line = String::new();
        let mut reader = BufReader::new(stream);
        loop {
            line.clear();
            if reader.read_line(&mut line).await? == 0 {
                return Err(std::io::Error::other("Player closed connection"));
            }
            let reply: serde_json::Value = serde_json::from_str(&line)?;
            if let Some(error) = reply["error"].as_str() {
                if error == "success" {
                    return Ok(());
                }
                return Err(std::io::Error::other(error.to_string()));
            }
        }
    };
    tokio::time::timeout(std::time::Duration::from_millis(800), action).await??;
    Ok(())
}

// ---------- utils ----------

fn short_id_input(webm: &Path) -> String {
    webm.file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default()
}

fn short_id(s: &str) -> String {
    let mut h = Sha256::new();
    h.update(s.as_bytes());
    let d = h.finalize();
    let hex: String = d.iter().map(|b| format!("{b:02x}")).collect();
    hex[..12].to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn old_library_state_keeps_cards_and_gets_geometry_defaults() {
        let store: Store = serde_json::from_str(r#"{"cards":[{"id":"old","file":"old.webm","thumb":"/media/old.png","duration_s":3.0,"has_alpha":true,"matted":true}],"playlists":{},"jobs":[]}"#).unwrap();
        assert_eq!(store.cards[0].id, "old");
        assert_eq!(store.overlay_height, 480);
        assert_eq!(store.overlay_corner, "br");
        assert_eq!(store.cards[0].name, "");
    }

    #[test]
    fn fresh_store_matches_loaded_store_geometry() {
        let store: Store =
            serde_json::from_str(r#"{"cards":[],"playlists":{},"jobs":[]}"#).unwrap();
        assert_eq!(Store::default().overlay_height, store.overlay_height);
        assert_eq!(Store::default().overlay_corner, store.overlay_corner);
    }
}
