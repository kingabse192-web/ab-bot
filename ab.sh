#!/bin/bash
DIR="/home/ab/ab-ai"
CMD="python3 main.py"

case "$1" in
  start)
    cd "$DIR"
    nohup $CMD > /tmp/ab_bot.log 2>&1 &
    echo "ab started (PID $!)"
    ;;
  stop)
    pkill -f "python3.*main.py" 2>/dev/null
    echo "ab stopped"
    ;;
  restart)
    $0 stop; sleep 1; $0 start
    ;;
  status)
    if pgrep -f "python3.*main.py" > /dev/null; then
      echo "ab: RUNNING"
    else
      echo "ab: STOPPED"
    fi
    ;;
  log)
    tail -f /tmp/ab_bot.log
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|log}"
    exit 1
esac
