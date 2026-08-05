#!/usr/bin/env python3
"""
Feed current Hermes session to MemOS for memory processing.
Run as cron: python3 ~/.hermes/scripts/feed_memos.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from memos_controller import MemOSController
from pathlib import Path
import json

def main():
    sessions_file = Path.home() / ".hermes" / "sessions" / "sessions.json"
    if not sessions_file.exists():
        print("No sessions file")
        return
    
    with open(sessions_file) as f:
        sessions = json.load(f)
    
    if not sessions:
        print("No active sessions")
        return
    
    ctrl = MemOSController()
    try:
        ctrl.start()
        ctrl.init()
        
        for key, sess in sessions.items():
            session_id = sess.get("session_id", "")
            if not session_id:
                continue
            
            sid = ctrl.open_session(session_id)
            display = sess.get("display_name") or "Hermes Chat"
            eid = ctrl.open_episode(sid, user_message=display)
            
            # Record as a turn
            ctrl.turn_start(sid, eid, display)
            ctrl.turn_end(sid, eid, f"Session: {session_id}")
            
            ctrl.submit_feedback(eid, "positive")
            ctrl.close_episode(eid)
            ctrl.close_session(sid)
            
            print(f"Fed: {session_id}")
    
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ctrl.shutdown()

if __name__ == "__main__":
    main()
# Kuma heartbeat
import subprocess
subprocess.run(["bash", "/home/ubuntu/.hermes/scripts/kuma_ping.sh", "MemOS Memory Feed"], capture_output=True)
