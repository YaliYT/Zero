#!/usr/bin/env bash
# ffmpeg toolbox for reels: cut, join, compress, convert.
#   ff.sh mp4      in.mov  [out.mp4]          any video -> H.264/AAC MP4 (MOV -> MP4)
#   ff.sh compress in.mp4  [out.mp4] [crf]    smaller file for Instagram/TikTok (crf 23 default)
#   ff.sh concat   out.mp4 a.mp4 b.mp4 ...     join clips (re-encodes, so mixed sources are fine)
#   ff.sh cut      in.mp4  START END [out]     trim, e.g. cut in.mp4 00:00:03 00:00:12
#   ff.sh audio    in.mp4  [out.wav]           extract 16 kHz mono WAV (for Whisper)
#   ff.sh mix      video.mp4 voice.mp3 [music.mp3] [out.mp4]   lay voice (+ music at -18 dB) under video
#   ff.sh vertical in.mp4  [out.mp4]           crop/scale to 1080x1920
#   ff.sh frames   in.mp4  [dir] [every_sec]   contact-sheet frames for review
set -euo pipefail
cmd=${1:-}; shift || true
V="-c:v libx264 -preset slow -pix_fmt yuv420p -movflags +faststart"
A="-c:a aac -b:a 192k -ar 48000"
case "$cmd" in
  mp4)      in=$1; out=${2:-${in%.*}.mp4}; ffmpeg -y -i "$in" $V -crf 18 $A "$out" ;;
  compress) in=$1; out=${2:-${in%.*}_small.mp4}; ffmpeg -y -i "$in" $V -crf "${3:-23}" -maxrate 8M -bufsize 16M $A "$out" ;;
  concat)   out=$1; shift; n=$#; inputs=(); filt=""
            for i in $(seq 0 $((n-1))); do filt+="[$i:v:0][$i:a:0]"; done
            for f in "$@"; do inputs+=(-i "$f"); done
            ffmpeg -y "${inputs[@]}" -filter_complex "${filt}concat=n=$n:v=1:a=1[v][a]" -map "[v]" -map "[a]" $V -crf 18 $A "$out" ;;
  cut)      in=$1; out=${4:-${in%.*}_cut.mp4}; ffmpeg -y -ss "$2" -to "$3" -i "$in" $V -crf 18 $A "$out" ;;
  audio)    in=$1; out=${2:-${in%.*}.wav}; ffmpeg -y -i "$in" -vn -ac 1 -ar 16000 "$out" ;;
  mix)      vid=$1; voice=$2; music=${3:-}; out=${4:-${vid%.*}_mixed.mp4}
            if [[ -n "$music" ]]; then
              ffmpeg -y -i "$vid" -i "$voice" -stream_loop -1 -i "$music" -filter_complex \
                "[2:a]volume=-18dB[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]" \
                -map 0:v -map "[a]" -shortest -c:v copy $A "$out"
            else
              ffmpeg -y -i "$vid" -i "$voice" -map 0:v -map 1:a -shortest -c:v copy $A "$out"
            fi ;;
  vertical) in=$1; out=${2:-${in%.*}_9x16.mp4}
            ffmpeg -y -i "$in" -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" $V -crf 18 $A "$out" ;;
  frames)   in=$1; dir=${2:-frames}; every=${3:-2}; mkdir -p "$dir"
            ffmpeg -y -loglevel error -i "$in" -vf "fps=1/$every,scale=360:-1,tile=4x2" "$dir/sheet_%02d.jpg"; ls "$dir" ;;
  *) sed -n 2,11p "$0"; exit 1 ;;
esac
