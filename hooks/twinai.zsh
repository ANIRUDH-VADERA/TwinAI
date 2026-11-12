# TwinAI terminal capture. Add to ~/.zshrc:  source /path/to/TwinAI/hooks/twinai.zsh
# Sends each finished command (and its exit code) to the local daemon in the background.
# Commands that start with a space are never captured, the same convention as HIST_IGNORE_SPACE.

typeset -g _TWINAI_CMD=""
typeset -g _TWINAI_PORT="${TWINAI_PORT:-7331}"
typeset -g _TWINAI_CONFIG="${TWINAI_ROOT:-$HOME/.twinai}/config.json"

_twinai_preexec() { _TWINAI_CMD="$1"; }

_twinai_precmd() {
  local exit_code=$?
  local cmd="$_TWINAI_CMD"
  _TWINAI_CMD=""
  [[ -z "$cmd" || "$cmd" == " "* || ! -r "$_TWINAI_CONFIG" ]] && return
  local token
  token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["token"])' "$_TWINAI_CONFIG" 2>/dev/null) || return
  # Build the JSON with python so quotes and backslashes in the command are escaped correctly.
  local body
  body=$(python3 -c 'import json,sys;print(json.dumps({"source":"terminal","content":sys.argv[1],"meta":{"exit_code":int(sys.argv[2]),"cwd":sys.argv[3]}}))' "$cmd" "$exit_code" "$PWD") || return
  ( curl -s -m 2 -o /dev/null -X POST "http://127.0.0.1:${_TWINAI_PORT}/capture" \
      -H "content-type: application/json" -H "x-twinai-token: ${token}" --data "$body" & ) 2>/dev/null
}

autoload -Uz add-zsh-hook
add-zsh-hook preexec _twinai_preexec
add-zsh-hook precmd _twinai_precmd
