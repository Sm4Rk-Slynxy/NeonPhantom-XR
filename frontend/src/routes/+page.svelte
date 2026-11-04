<script>
  import { onMount } from 'svelte';
  let library = $state([]), playlists = $state([]), favorites = $state([]), jobs = $state([]);
  let connected = $state(false), mode = $state('auto'), search = $state(''), filter = $state('all');
  let aiQuality = $state('detailed');
  let cutoutModel = $state('legacy'), subject = $state('person'), models = $state([]);
  let inputProjection = $state('flat');
  $effect(() => { if(inputProjection !== 'flat') prepareVR=false; });
  let prepareVR = $state(false), stereoDevice = $state('auto');
  let previewOnly = $state(false), preferencesLoaded = $state(false);
  let restrictRegion = $state(false), region = $state([0, 0, 100, 100]);
  const modelLabels = {'legacy':'Classic cutout', 'matanyone2':'MatAnyone 2 · people', 'wevisone-2b':'WeVisOne 2B · experimental', 'wevisone-4b':'WeVisOne 4B · experimental'};
  let selectedModel = $derived(models.find(m => m.id === cutoutModel));
  let needsModel = $derived(['auto','ai'].includes(mode) && cutoutModel !== 'legacy' && !selectedModel?.installed);
  let installing = $derived(jobs.some(j => j.install && ['queued','running'].includes(j.state)));
  let subjectBox = $derived(['auto','ai'].includes(mode) && cutoutModel === 'matanyone2' && restrictRegion ? region.map(n => Number(n)/100) : null);
  let optionsValid = $derived((!['auto','ai'].includes(mode) || !cutoutModel.startsWith('wevisone') || (subject.trim().length > 0 && subject.trim().length <= 200)) && (!subjectBox || (subjectBox.every(n => Number.isFinite(n) && n >= 0 && n <= 1) && subjectBox[0] < subjectBox[2] && subjectBox[1] < subjectBox[3])));
  $effect(() => { if (preferencesLoaded) { try { localStorage.setItem('deskdance.import', JSON.stringify({mode, model:cutoutModel, quality:aiQuality, subject, prepareVR, stereoDevice, inputProjection})); } catch {} } });
  function modelOptions(includePreview = true) { return {model:cutoutModel, subject:subject.trim() || 'person', prepare_stereo:prepareVR, stereo_device:stereoDevice, projection:inputProjection, ...(subjectBox ? {subject_box:subjectBox} : {}), ...(includePreview && previewOnly ? {preview_seconds:3} : {})}; }
  async function refreshModels() { try { models = await api('/models'); } catch (e) { message = e.message; } }

  let segmentInit = $state(null), segmentFiles = $state([]), initLocalPath = $state('');
  let importPath = $state(''), playlistName = $state(''), message = $state('');
  let uploading = $state(false), uploadProgress = $state(0), uploadName = $state(''), dragging = $state(false);
  let stage = $state({ playing: false, card_id: null, height_px: 480, corner: 'br' });
  let height = $state(480), corner = $state('br'), busy = $state(false), preview = $state(null), health = $state(null);
  let previewDialog = $state();
  $effect(() => { if (preview && previewDialog && !previewDialog.open) previewDialog.showModal(); });
  let uploadEl, ws, reconnect, poll, disposed = false;
  const modes = [
    ['auto', 'Auto cutout', 'Keep existing transparency; otherwise remove the background with AI.'],
    ['ai', 'AI cutout', 'Remove the background with the selected cutout model.'],
    ['green', 'Green screen', 'Remove a solid green background. Fast, with no AI setup.'],
    ['blue', 'Blue screen', 'Remove a solid blue background. Fast, with no AI setup.'],
    ['alpha', 'Preserve transparency', 'Use a video that already includes an alpha channel.'],
    ['keep', 'Keep background', 'Convert and play the full video, with its background visible.']
  ];
  let visible = $derived(library.filter(c =>
    (filter === 'all' || (filter === 'favorites' ? favorites.includes(c.id) : playlists.find(p => 'playlist:' + p.name === filter)?.cards.includes(c.id))) &&
    (c.name || c.file).toLowerCase().includes(search.toLowerCase())));
  let current = $derived(library.find(c => c.id === stage.card_id));
  let recentJobs = $derived([...jobs].reverse().slice(0, 8));
  let activeCount = $derived(jobs.filter(j => ['queued', 'running'].includes(j.state)).length);
  function title(c) { return c?.name || c?.file || 'Nothing playing'; }
  function duration(seconds) { const n = Math.round(seconds || 0); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`; }
  async function api(path, body, method = 'GET') {
    const r = await fetch('/api' + path, { method, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
    return data;
  }
  async function refresh() {
    try {
      [library, playlists, favorites, jobs, stage] = await Promise.all(['/library', '/playlists', '/favorites', '/jobs', '/stage'].map(p => api(p)));
      connected = true;
      if (health?.features?.model_picker) await refreshModels();
    } catch { connected = false; }
  }
  async function action(fn) {
    message = ''; busy = true;
    try { await fn(); await refresh(); } catch (e) { message = e.message; }
    finally { busy = false; }
  }
  function connect() {
    if (disposed) return;
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onopen = refresh;
    ws.onmessage = e => {
      const event = JSON.parse(e.data);
      if (event.type === 'stage_error') message = event.error;
      if (event.type === 'stage_state') stage = { ...stage, playing: event.playing, card_id: event.card_id };
      else if (event.type === 'job_progress') {
        if (jobs.some(j => j.job_id === event.job_id)) jobs = jobs.map(j => j.job_id === event.job_id ? { ...j, ...event } : j);
        else refresh();
      } else if (event.type !== 'hello') refresh();
    };
    ws.onclose = () => { if (!disposed) reconnect = setTimeout(connect, 2500); };
    ws.onerror = () => ws.close();
  }
  function sendFile(file, selectedMode, init = null, segments = []) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const options = new URLSearchParams({mode:selectedMode, quality:aiQuality, ...modelOptions(!init && !segments.length)});
      if (subjectBox) options.set('subject_box', JSON.stringify(subjectBox));
      if (init || segments.length) options.set('segments', 'true');
      xhr.open('POST', `/api/upload?${options}`);
      xhr.upload.onprogress = e => { if (e.lengthComputable) uploadProgress = Math.round(e.loaded / e.total * 100); };
      xhr.onload = () => {
        let data; try { data = JSON.parse(xhr.responseText); } catch { data = {}; }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(data.error || `Upload failed (${xhr.status})`));
      };
      xhr.onerror = () => reject(new Error('Connection lost during upload. Try again.'));
      const form = new FormData(); if (init) form.append('init', init); form.append('file', file); for (const segment of segments) form.append('file', segment); xhr.send(form);
    });
  }
  async function upload(files) {
    if (uploading || !connected || needsModel || !optionsValid) return;
    const selectedMode = mode;
    uploading = true; message = '';
    for (const file of Array.from(files || [])) {
      uploadName = file.name; uploadProgress = 0;
      if (!file.size || file.size > 2 * 1024 ** 3) { message = `${file.name}: select a nonempty video smaller than 2 GiB.`; continue; }
      try { await sendFile(file, selectedMode); await refresh(); }
      catch (e) { message = `${file.name}: ${e.message}`; }
    }
    uploading = false; if (uploadEl) uploadEl.value = '';
  }
  async function importSegments() {
    if (!segmentFiles.length || uploading || !connected || !health?.features?.m4s_segments) return;
    const files = [...segmentFiles].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    if (files.reduce((n, f) => n + f.size, segmentInit?.size || 0) > 2 * 1024 ** 3) { message = 'Combined M4S import exceeds 2 GiB.'; return; }
    uploading = true; uploadName = `${files.length} M4S segment(s)`; uploadProgress = 0; message = '';
    try { await sendFile(files[0], mode, segmentInit, files.slice(1)); await refresh(); }
    catch (e) { message = e.message; }
    finally { uploading = false; }
  }
  function play(id) { return action(() => api('/stage/play', { card_id: id }, 'POST')); }
  function favorite(id) { return action(() => api('/favorites', { card_id: id }, 'POST')); }
  function add(id, name) { return action(() => api(`/playlists/${encodeURIComponent(name)}/add`, { card_id: id }, 'POST')); }
  function remove(c) { if (confirm(`Delete “${title(c)}” and its converted video?`)) action(() => api(`/cards/${c.id}`, undefined, 'DELETE')); }
  onMount(() => {
    disposed = false;
    try {
      const saved = JSON.parse(localStorage.getItem('deskdance.import') || '{}');
      if (modelLabels[saved.model]) cutoutModel = saved.model;
      if (['fast','detailed'].includes(saved.quality)) aiQuality = saved.quality;
      if (modes.some(m => m[0] === saved.mode)) mode = saved.mode;
      if (['flat','vr180-sbs'].includes(saved.inputProjection)) inputProjection=saved.inputProjection;
      if (typeof saved.prepareVR === 'boolean') prepareVR = saved.prepareVR;
      if (['auto','gpu','cpu'].includes(saved.stereoDevice)) stereoDevice = saved.stereoDevice;
      if (typeof saved.subject === 'string' && saved.subject.trim()) subject = saved.subject;
    } catch {}
    preferencesLoaded = true;
    refreshModels();
    refresh().then(() => { height = stage.height_px; corner = stage.corner; });
    api('/health').then(data => health = data).catch(() => {});
    connect(); poll = setInterval(refresh, 5000);
    return () => { disposed = true; clearTimeout(reconnect); clearInterval(poll); if (ws) { ws.onclose = null; ws.close(); } };
  });
</script>

<svelte:head><title>NeonPhantom XR — Studio</title><meta name="description" content="Local video cutouts, stereo depth, desktop overlays, and Quest passthrough." /></svelte:head>

<header class="topbar">
  <a href="/" class="brand" aria-label="NeonPhantom XR Studio"><svg class="brand-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M3 12V3h9M20 3h9v9M29 20v9h-9M12 29H3v-9" stroke="currentColor" stroke-width="2"/><path d="M10 23V9l12 14V9" stroke="currentColor" stroke-width="2"/></svg><span>NEONPHANTOM</span><span class="xr-tag">XR</span><span class="brand-label">STUDIO / 01</span></a>
  <div class="header-actions"><a class="quest-link" href="https://localhost:8443/" target="_blank" rel="noopener" title="Run start-quest.sh or start-quest.cmd to open the local Quest viewer">Quest viewer ↗</a><span class="connection"><i class:online={connected}></i>{connected ? 'Studio connected' : 'Server offline'}</span></div>
</header>
<main class="shell">
  <aside class="sidebar">
    <p class="eyebrow">WORKSPACE</p>
    <button class:active={filter === 'all'} class="nav" onclick={() => filter = 'all'}><span>▦ &nbsp; All videos</span><span>{library.length}</span></button>
    <button class:active={filter === 'favorites'} class="nav" onclick={() => filter = 'favorites'}><span>☆ &nbsp; Favorites</span><span>{favorites.length}</span></button>
    <div class="side-heading"><p class="eyebrow">PLAYLISTS</p><span>{playlists.length}</span></div>
    {#each playlists as pl}
      <div class="playlist-row"><button class:active={filter === 'playlist:' + pl.name} class="nav" onclick={() => filter = 'playlist:' + pl.name}><span>♫ &nbsp; {pl.name}</span><span>{pl.cards.length}</span></button><button class="icon subtle" aria-label={`Delete playlist ${pl.name}`} onclick={() => { if (confirm(`Delete playlist “${pl.name}”?`)) action(async () => { await api(`/playlists/${encodeURIComponent(pl.name)}`, undefined, 'DELETE'); filter = 'all'; }); }}>×</button></div>
    {/each}
    <form class="playlist-form" onsubmit={e => { e.preventDefault(); action(async () => { await api('/playlists', { name: playlistName.trim() }, 'POST'); playlistName = ''; }); }}>
      <input aria-label="New playlist name" placeholder="New playlist…" bind:value={playlistName} maxlength="80" /><button class="icon" aria-label="Create playlist" disabled={!connected || !playlistName.trim()}>+</button>
    </form>
    <div class="side-note"><span class="signal-line"></span><strong>LOCAL ENGINE</strong><p>Desktop + spatial video</p><span class="build-label">V0.1 / ALPHA</span></div>
  </aside>

  <section class="workspace" aria-label="Video library">
    <div class="intro"><div><p class="eyebrow">VIDEO WORKSPACE</p><h1>Studio<span class="title-dot">.</span></h1><p>Remove backgrounds. Prepare depth. Play in your space.</p></div><span class="version"><i></i> ON-DEVICE PROCESSING</span></div>
    {#if !connected}<div class="notice">Start the app with <code>start-windows.cmd</code> on Windows or <code>./start.sh</code> on Linux, then reconnect here.</div>{/if}
    {#if message}<div class="notice" role="alert"><span>{message}</span><button class="icon" aria-label="Dismiss message" onclick={() => message = ''}>×</button></div>{/if}
    {#if health && Object.values(health.tools).some(ok => !ok)}<div class="notice">Missing tools: {Object.entries(health.tools).filter(([, ok]) => !ok).map(([name]) => name).join(', ')}. See the setup guide before importing or playing.</div>{/if}
    <div class="import-panel" class:dragging role="region" aria-label="Upload videos" ondragover={e => { e.preventDefault(); dragging = true; }} ondragleave={e => { if (!e.currentTarget.contains(e.relatedTarget)) dragging = false; }} ondrop={e => { e.preventDefault(); dragging = false; upload(e.dataTransfer.files); }}>
      <div class="upload-copy"><div class="upload-symbol" aria-hidden="true">↥</div><div><p class="section-index">01 / IMPORT</p><h2>{uploading ? `Uploading · ${uploadProgress}%` : 'Drop footage here'}</h2><p>{uploading ? uploadName : 'MP4, MOV, MKV, WebM + more · 2 GiB per file'}</p></div><button class="primary" disabled={!connected || uploading || needsModel || !optionsValid} onclick={() => uploadEl.click()}>{uploading ? 'Uploading…' : 'Add videos ↗'}</button></div>
      <input type="file" accept="video/*,.mp4,.mov,.mkv,.webm,.avi,.m4v,.wmv,.flv,.mpeg,.mpg,.ts,.mts,.m2ts,.ogv,.gif,.m4s" multiple hidden bind:this={uploadEl} onchange={e => upload(e.target.files)} />
      <div class="import-options"><label for="input-projection">Video source</label><select id="input-projection" bind:value={inputProjection} disabled={uploading}><option value="flat">Normal 2D video</option><option value="vr180-sbs">Headset-ready VR180 SBS</option></select><p>{inputProjection === 'vr180-sbs' ? 'Equirectangular 180° side-by-side. Choose AI cutout to keep people in passthrough; each eye is processed separately and its captured stereo is retained. Raw fisheye is not supported.' : 'A normal video screen or cutout. Optionally estimate depth to prepare a 3D SBS version.'}</p></div>
      <div class="import-options"><label for="mode">Background</label><select id="mode" bind:value={mode} disabled={uploading}>{#each modes as [value, label]}<option {value}>{label}</option>{/each}</select><p>{modes.find(m => m[0] === mode)[2]}</p></div>
      {#if ['auto','ai'].includes(mode)}
        <div class="import-options model-options">
          <label for="cutout-model">Cutout model</label>
          <select id="cutout-model" bind:value={cutoutModel} disabled={uploading}>
            {#each Object.entries(modelLabels) as [value, label]}<option {value}>{label}</option>{/each}
          </select>
          <span class:installed={selectedModel?.installed} class="model-status">{selectedModel?.installed ? 'Installed' : cutoutModel === 'legacy' ? 'Available with AI setup' : 'Download required'}</span>
          {#if cutoutModel !== 'legacy'}<button disabled={!connected || uploading || installing || busy} onclick={() => action(() => api(`/models/${cutoutModel}/install`, {}, 'POST'))}>{installing ? 'Installation queued / running…' : selectedModel?.installed ? 'Repair installation' : 'Download & install'}</button>{/if}
        </div>
        <p class="hint">{cutoutModel === 'legacy' ? 'The existing cutout engine. Detailed targets people; Fast uses the small general model.' : cutoutModel === 'matanyone2' ? 'Video matting for people. Starts from an automatic person mask, then carries it through the clip. Try a preview first.' : 'Describe the subject to keep. Processes each frame independently; edges or subject selection may flicker. GPU recommended; try a preview first.'}</p>
        {#if cutoutModel.startsWith('wevisone')}
          <div class="import-options"><label for="subject">Keep this subject</label><input id="subject" bind:value={subject} maxlength="200" placeholder="the penguin" disabled={uploading} /><p>Matching subjects are kept; when none is found, that frame is transparent.</p></div>
        {/if}
        {#if cutoutModel === 'matanyone2'}
          <details><summary>First-frame person region (optional)</summary><label class="check-option"><input type="checkbox" bind:checked={restrictRegion} disabled={uploading} /> Restrict the automatic starting mask</label>
            {#if restrictRegion}<div class="region-fields">{#each ['Left %','Top %','Right %','Bottom %'] as label, i}<label>{label}<input type="number" min="0" max="100" bind:value={region[i]} disabled={uploading} /></label>{/each}</div><p class="hint">Coordinates are percentages of the first frame. Left must be below Right; Top must be below Bottom.</p>{/if}
          </details>
        {/if}
      {/if}
      <label class="check-option"><input type="checkbox" bind:checked={prepareVR} disabled={uploading || !health?.features?.auto_stereo || inputProjection!=='flat'} /> Prepare a 3D SBS VR version after import</label>
      {#if prepareVR}<div class="import-options"><label for="stereo-device">VR depth processing</label><select id="stereo-device" bind:value={stereoDevice} disabled={uploading}><option value="auto">Auto · prefer GPU</option><option value="gpu">GPU preferred · CPU fallback</option><option value="cpu">CPU only</option></select><p>Keep the Quest companion running. It prepares stereo after PC imports finish, then shows it in the headset library. Choose Keep background above for a full movie.</p></div>{/if}
      <label class="check-option"><input type="checkbox" bind:checked={previewOnly} disabled={uploading} /> Preview only · first 3 seconds (complete videos)</label>
      <p class="hint">{previewOnly ? 'Creates a separate clip labeled Preview. Turn this off and upload again to import the full video.' : 'Full import · keeps the entire clip duration.'}</p>
      {#if !optionsValid}<p class="hint" role="alert">Enter a subject and valid region coordinates before importing.</p>{/if}
      {#if ['auto','ai'].includes(mode)}<div class="import-options"><label for="ai-quality">AI processing</label><select id="ai-quality" bind:value={aiQuality} disabled={uploading || !health?.features?.fast_ai}><option value="detailed">Detailed · 30 fps / 720 px</option><option value="fast">Fast · 12 fps / 480 px</option></select><p>{aiQuality === 'fast' ? 'Processes up to 12 fps at 480 px. Classic also uses a smaller model. Full imports preserve duration.' : 'Processes up to 30 fps at 720 px. Full imports preserve duration.'}</p></div>{/if}
      {#if uploading}<progress value={uploadProgress} max="100" aria-label="Upload progress"></progress>{/if}
      <details class="segment-import"><summary>Import M4S video segments</summary>
        {#if !health?.features?.m4s_segments}<p class="hint">Restart the app to activate M4S segment support.</p>{/if}
        <p class="hint">Select video segments from one stream. They are joined in filename order (1, 2, 10). Include every consecutive segment to keep the full video.</p>
        <label for="segment-init">Initialization file (usually init.mp4 or init.m4s)</label>
        <input id="segment-init" type="file" accept=".mp4,.m4s" disabled={uploading} onchange={e => segmentInit = e.target.files?.[0] || null} />
        <label for="segment-files">Video segments (.m4s)</label>
        <input id="segment-files" type="file" accept=".m4s,.mp4" multiple disabled={uploading} onchange={e => segmentFiles = Array.from(e.target.files || [])} />
        {#if segmentFiles.length}<p class="hint">Order: {[...segmentFiles].sort((a,b) => a.name.localeCompare(b.name, undefined, {numeric:true})).map(f => f.name).join(' → ')}</p>{/if}
        <button class="wide" disabled={!connected || uploading || !segmentFiles.length || !health?.features?.m4s_segments || needsModel || !optionsValid} onclick={importSegments}>Import as one video</button>
        <p class="hint">Self-contained M4S files also work with Add videos. Separate fragments need the matching initialization file. Choose Auto cutout to remove a background, or Keep background for normal playback.</p>
      </details>
      <details><summary>Import from a local path</summary><form class="path-form" onsubmit={e => { e.preventDefault(); action(async () => { await api('/import', { path: importPath.trim(), mode, quality: aiQuality, ...modelOptions(), ...(initLocalPath.trim() ? { init_path: initLocalPath.trim() } : {}) }, 'POST'); importPath = ''; }); }}><input aria-label="Absolute video path" placeholder="Absolute video path (Linux or Windows)" bind:value={importPath} /><input aria-label="Optional M4S initialization path" placeholder="Optional: /path/to/init.mp4" bind:value={initLocalPath} /><button disabled={!connected || !importPath.trim() || needsModel || !optionsValid || (previewOnly && !!initLocalPath.trim())}>Import</button></form></details>
    </div>
    <div class="library-heading"><div><h2>{filter === 'all' ? 'Library' : filter === 'favorites' ? 'Favorites' : filter.slice(9)}</h2><span>{String(visible.length).padStart(2,'0')}</span></div><div class="library-tools"><input type="search" aria-label="Search videos" placeholder="Search library" bind:value={search} /><button disabled={!connected || busy || !visible.length} onclick={() => action(() => api('/stage/shuffle', { card_ids: visible.map(c => c.id) }, 'POST'))}>⇄ Shuffle</button></div></div>
    <div class="grid">
      {#each visible as card}
        <article class="card" class:playing={stage.playing && stage.card_id === card.id}>
          <button class="thumbnail checker" aria-label={`Preview ${title(card)}`} disabled={card.available === false} onclick={() => preview = card}><img src={card.thumb} alt={title(card)} loading="lazy" onerror={e => e.currentTarget.style.visibility = 'hidden'} /><span class="duration">{duration(card.duration_s)}</span><span class="preview-label">▷ Preview</span></button>
          <div class="card-info"><h3 title={title(card)}>{title(card)}</h3><p><span class="alpha-dot" class:opaque={!card.has_alpha}></span>{card.available === false ? 'File missing · import again' : card.has_alpha ? 'Transparent' : 'Full video'}{stage.playing && stage.card_id === card.id ? ' · On desktop' : ''}</p>{#if card.model}<p>{modelLabels[card.model] || card.model}{card.preview ? ' · Preview' : ''}</p>{/if}</div>
          <div class="card-actions"><button class="play-button" disabled={!connected || busy || card.available === false} onclick={() => play(card.id)}>▶ Play on desktop</button><button class="icon" class:starred={favorites.includes(card.id)} aria-label={`Favorite ${title(card)}`} aria-pressed={favorites.includes(card.id)} disabled={busy} onclick={() => favorite(card.id)}>☆</button><button class="icon subtle" aria-label={`Delete ${title(card)}`} disabled={busy} onclick={() => remove(card)}>×</button></div>
          {#if playlists.length}<select class="add-playlist" aria-label={`Add ${title(card)} to a playlist`} disabled={busy} onchange={e => { if (e.target.value) add(card.id, e.target.value); e.target.value = ''; }}><option value="">+ Add to playlist</option>{#each playlists as pl}<option value={pl.name}>{pl.name}</option>{/each}</select>{/if}
        </article>
      {:else}
        <div class="empty-state"><span class="empty-frame" aria-hidden="true"><i></i></span><h2>{search || filter !== 'all' ? 'No matching videos' : 'No footage yet'}</h2><p>{filter !== 'all' ? 'Add videos from All videos using each card’s playlist menu.' : search ? 'Try another search.' : 'Choose your import settings above, then add a video.'}</p><span class="empty-caption">CUTOUT / STEREO / PASSTHROUGH</span></div>
      {/each}
    </div>

  </section>

  <aside class="controls">
    <div class="panel"><div class="panel-heading"><h2>Desktop stage</h2><span class="live" class:on={stage.playing}>{stage.playing ? 'LIVE' : 'IDLE'}</span></div><div class="stage-preview checker">{#if current}<img src={current.thumb} alt={title(current)} />{:else}<span>◈</span><p>Desktop output preview</p>{/if}<div class="desktop-bar"><i></i><i></i><i></i><span></span><i></i></div></div><h3 class="now-playing">{title(current)}</h3><p class="muted">{stage.playing ? 'Looping above your desktop' : 'Choose a video to start'}</p><button class="stop" disabled={!stage.playing || busy} onclick={() => action(() => api('/stage/stop', {}, 'POST'))}>■ Stop playback</button><div class="divider"></div><label class="setting" for="height">Overlay height <span>{height} px</span></label><input id="height" type="range" min="160" max="1600" step="20" bind:value={height} /><label class="setting" for="corner">Position</label><select id="corner" bind:value={corner}><option value="br">Bottom right · near taskbar</option><option value="bl">Bottom left · near taskbar</option><option value="tr">Top right</option><option value="tl">Top left</option></select><button class="wide" disabled={!connected || busy} onclick={() => action(() => api('/stage/geometry', { height_px: Number(height), corner }, 'POST'))}>Apply position & size</button><p class="hint">Borderless, muted and always on top. Background transparency depends on your desktop compositor.</p></div>
    <div class="panel"><h2>Quest passthrough</h2><p class="hint">Run <strong>start-quest.sh</strong> (Linux) or <strong>start-quest.cmd</strong> (Windows). In Quest Browser on the same Wi-Fi, open the HTTPS address printed on your PC and enter its pairing code.</p><p class="hint">Choose a prepared video, then Enter passthrough. The PC handles cutouts; your headset handles playback.</p></div>
    <div class="panel processing"><div class="panel-heading"><h2>Import activity</h2><span class="muted">{activeCount} active</span></div>{#each recentJobs as job}<div class="job"><div class="job-heading"><strong title={job.name || job.input}>{job.name || job.input?.split('/').pop() || job.job_id}</strong><span class:error={job.state === 'error'}>{job.state === 'done' ? '✓' : job.state === 'error' ? 'Failed' : `${Math.round(job.progress * 100)}%`}</span></div><p>{job.state === 'error' ? job.error || 'Import failed. Please try again.' : job.phase || job.state}</p>{#if health?.features?.retry_imports && job.state === 'error'}<div class="job-actions">{#if job.can_retry}<button disabled={busy || (!job.install && needsModel)} onclick={() => action(() => api(`/jobs/${job.job_id}/retry`, { mode, quality: aiQuality, ...modelOptions(false) }, 'POST'))}>Retry · {job.install ? 'installation' : modes.find(m => m[0] === mode)[1]}</button>{/if}<button disabled={busy} onclick={() => { if (confirm('Remove this failed import and any retained upload?')) action(() => api(`/jobs/${job.job_id}`, undefined, 'DELETE')); }}>Remove</button></div>{/if}{#if ['running', 'queued'].includes(job.state)}<progress value={job.progress} max="1" aria-label={`Import progress for ${job.name}`}></progress>{/if}</div>{:else}<p class="hint">No queued imports.</p>{/each}</div>
    <p class="local-note">VIDEO PROCESSING STAYS LOCAL.<br />AI models may download on first use.</p>
  </aside>
</main>
{#if preview}<dialog class="modal" bind:this={previewDialog} onclose={() => preview = null} oncancel={() => preview = null} aria-label={`Preview ${title(preview)}`}><div class="panel-heading"><h2>{title(preview)}</h2><button class="icon" aria-label="Close preview" onclick={() => preview = null}>×</button></div><video class="checker" src={`/media/${preview.file}`} controls autoplay loop muted playsinline></video><p class="hint">The checkerboard shows the transparent area. Desktop playback uses a separate borderless window.</p><button class="primary" disabled={busy} onclick={() => { play(preview.id); preview = null; }}>▶ Play on desktop</button></dialog>{/if}
