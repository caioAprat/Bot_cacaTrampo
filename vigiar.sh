#!/usr/bin/env bash
# Roda o caçador a cada 10 min, das 7h às 23h (Brasília), por até 5h40.
# Depois de cada rodada, guarda os projetos já vistos no repositório.

DURACAO=$((340 * 60))
FIM=$(( $(date +%s) + DURACAO ))

git config user.name "cacador-bot"
git config user.email "cacador-bot@users.noreply.github.com"

while [ "$(date +%s)" -lt "$FIM" ]; do
  HORA=$(TZ=America/Sao_Paulo date +%-H)
  if [ "$HORA" -ge 7 ] && [ "$HORA" -lt 23 ]; then
    echo "=== $(TZ=America/Sao_Paulo date '+%d/%m %H:%M')"
    python cacador.py || echo "[aviso] a rodada falhou, tento de novo daqui a 10 min"
    git add vistos.json agenda.json
    if ! git diff --cached --quiet; then
      git commit -q -m "vistos"
      git pull -q --rebase origin main && git push -q || echo "[aviso] não consegui salvar os vistos"
    fi
  fi
  sleep 600
done
