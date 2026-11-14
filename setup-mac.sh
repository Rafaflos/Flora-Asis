#!/bin/bash
# Flora · configuración en un paso para macOS.
# Instala dependencias, crea los entornos, genera el token compartido y te pide
# la clave de la API de Claude sin mostrarla en pantalla. Se puede repetir sin riesgo.
set -euo pipefail
cd "$(dirname "$0")"

set_kv() {  # set_kv archivo CLAVE valor  -> reemplaza o añade la línea CLAVE=valor
  local file=$1 key=$2 value=$3
  touch "$file"
  grep -v "^${key}=" "$file" > "$file.tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$file.tmp"
  mv "$file.tmp" "$file"
}
get_kv() { grep "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- || true; }

PY=$(command -v python3.11 || command -v python3)
if [[ "${FLORA_SKIP_INSTALL:-0}" != 1 ]]; then
  if [[ "$(uname)" == Darwin ]]; then
    command -v brew >/dev/null || { echo "Falta Homebrew. Instálalo desde https://brew.sh y vuelve a ejecutar."; exit 1; }
    echo "== Instalando dependencias del sistema =="
    brew install python@3.11 portaudio ffmpeg
    PY="$(brew --prefix)/bin/python3.11"
  fi
  for dir in backend-mac desktop-node; do
    echo "== Entorno de $dir =="
    "$PY" -m venv "$dir/.venv"
    "$dir/.venv/bin/pip" install --quiet --upgrade pip
    "$dir/.venv/bin/pip" install --quiet -r "$dir/requirements.txt"
  done
fi

for dir in backend-mac desktop-node; do
  [[ -f "$dir/.env" ]] || cp "$dir/.env.example" "$dir/.env"
  chmod 600 "$dir/.env"
done

# Token compartido entre backend, nodo de escritorio y Android
TOKEN=$(get_kv backend-mac/.env FLORA_TOKEN)
if [[ -z "$TOKEN" || "$TOKEN" == pega_aqui* ]]; then
  TOKEN=$(openssl rand -hex 24)
fi
set_kv backend-mac/.env FLORA_TOKEN "$TOKEN"
set_kv desktop-node/.env FLORA_TOKEN "$TOKEN"

# Clave de la API de Claude (entrada oculta; Enter la deja como está)
CURRENT=$(get_kv backend-mac/.env ANTHROPIC_API_KEY)
if [[ -n "$CURRENT" && "$CURRENT" != "sk-ant-..." ]]; then
  PROMPT="Clave de la API de Claude ya guardada. Pega otra para cambiarla o pulsa Enter: "
else
  PROMPT="Pega tu clave de la API de Claude (console.anthropic.com > API keys) y pulsa Enter: "
fi
read -rsp "$PROMPT" KEY || true
echo
if [[ -n "${KEY:-}" ]]; then
  [[ "$KEY" == sk-ant-* ]] || echo "Aviso: la clave no empieza por sk-ant-; revísala si Flora no responde."
  set_kv backend-mac/.env ANTHROPIC_API_KEY "$KEY"
  echo "Clave guardada en backend-mac/.env"
elif [[ -z "$CURRENT" || "$CURRENT" == "sk-ant-..." ]]; then
  echo "Sin clave: Flora arrancará pero no podrá responder hasta que la añadas."
fi

# Android: IP de la Mac y token
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "IP_DE_TU_MAC")
PROPS=android-app/local.properties
set_kv "$PROPS" flora.serverUrl "ws://$IP:8765/ws"
set_kv "$PROPS" flora.token "$TOKEN"
[[ -n "$(get_kv "$PROPS" picovoice.accessKey)" ]] || set_kv "$PROPS" picovoice.accessKey ""
chmod 600 backend-mac/.env desktop-node/.env "$PROPS"

cat <<MSG

Listo. Siguientes pasos:
  1. Cerebro:        cd backend-mac && .venv/bin/python server.py
  2. Panel en vivo:  http://127.0.0.1:8765/panel
     Token del panel (FLORA_TOKEN): $TOKEN
  3. Nodo por teclado: cd desktop-node && .venv/bin/python listener.py --text
  4. Nodo por voz:     cd desktop-node && .venv/bin/python listener.py
  5. Android: añade picovoice.accessKey en android-app/local.properties (servidor: ws://$IP:8765/ws)
MSG
