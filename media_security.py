"""FFmpeg input policy: local video containers, never playlists or network URLs."""

# image2 and rawvideo are needed for our generated frames and pipes. Input
# playlists (hls, concat, dash) are deliberately absent: they can read unrelated
# files or open remote resources while decoding an apparently local upload.
INPUT_FORMATS = ('mov,matroska,webm,avi,asf,flv,mpeg,mpegts,mpegvideo,'
                 'gif,apng,ogg,nut,h264,hevc,obu,ivf,mjpeg,image2,rawvideo')


def local_media_command(command):
    command = list(command)
    if not command or command[0] not in ('ffmpeg', 'ffprobe'):
        return command
    policy = ['-protocol_whitelist', 'file,pipe,fd', '-format_whitelist', INPUT_FORMATS]
    if command[0] == 'ffprobe':
        return [command[0], *policy, *command[1:]]
    result = []
    for arg in command:
        if arg == '-i':
            result.extend(policy)
        result.append(arg)
    return result
