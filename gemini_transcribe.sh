#!/usr/bin/env bash
# transcribe.sh — Transcribe audio files using Gemini API
# Usage: transcribe.sh <audio_file> [language_hint]
# Example: transcribe.sh voice.ogg
#          transcribe.sh meeting.m4a en
#
# Requires: ffmpeg, curl, python3
# Environment: GEMINI_API_KEY (falls back to GOOGLE_API_KEY)

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: transcribe.sh <audio_file> [language_hint]" >&2
    echo "  language_hint: e.g. zh, en, ja (optional, auto-detected if omitted)" >&2
    exit 1
fi

INPUT="$1"
LANG_HINT="${2:-}"

if [[ ! -f "$INPUT" ]]; then
    echo "Error: file not found: $INPUT" >&2
    exit 1
fi

# Resolve API key
API_KEY="${GEMINI_API_KEY:-${GOOGLE_API_KEY:-}}"
if [[ -z "$API_KEY" ]]; then
    echo "Error: set GEMINI_API_KEY or GOOGLE_API_KEY" >&2
    exit 1
fi

# Temp files
TMPMP3=$(mktemp /tmp/transcribe.XXXXXX.mp3)
TMPJSON=$(mktemp /tmp/transcribe.XXXXXX.json)
trap 'rm -f "$TMPMP3" "$TMPJSON"' EXIT

# Convert to mp3
ffmpeg -i "$INPUT" -ar 16000 -ac 1 -q:a 9 "$TMPMP3" -y -loglevel error

# Build prompt
if [[ -n "$LANG_HINT" ]]; then
    PROMPT="Transcribe this audio verbatim. The language is $LANG_HINT. Output only the transcript text, nothing else."
else
    PROMPT="Transcribe this audio verbatim. Output only the transcript text, nothing else."
fi

# Build request JSON with python (handles large base64 safely)
python3 -c "
import json, base64, sys

with open(sys.argv[1], 'rb') as f:
    audio_b64 = base64.b64encode(f.read()).decode()

payload = {
    'contents': [{'parts': [
        {'text': sys.argv[2]},
        {'inline_data': {'mime_type': 'audio/mpeg', 'data': audio_b64}}
    ]}]
}

with open(sys.argv[3], 'w') as f:
    json.dump(payload, f)
" "$TMPMP3" "$PROMPT" "$TMPJSON"

# Call Gemini API
RESPONSE=$(curl -s "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key=${API_KEY}" \
    -H "Content-Type: application/json" \
    -d @"$TMPJSON")

# Extract text
python3 -c "
import json, sys
r = json.loads(sys.argv[1])
if 'candidates' in r:
    print(r['candidates'][0]['content']['parts'][0]['text'])
else:
    print('Error: ' + json.dumps(r, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)
" "$RESPONSE"
