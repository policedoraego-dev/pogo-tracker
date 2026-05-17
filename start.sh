#!/bin/bash
cd "$(dirname "$0")"
echo "ポケモンGO イベントトラッカーを起動中..."
python3 server.py &
SERVER_PID=$!
sleep 2
open http://localhost:3001
echo "ブラウザで開きました → http://localhost:3001"
echo "停止するには Ctrl+C"
wait $SERVER_PID
