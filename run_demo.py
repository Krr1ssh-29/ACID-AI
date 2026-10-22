#!/usr/bin/env python3
"""Convenience launcher for the hackathon presentation demo dashboard.

Usage:
    python run_demo.py [--port 5000] [--host 127.0.0.1]
"""
import argparse
import sys
from dashboard.app import create_app


def main():
    parser = argparse.ArgumentParser(
        description="Launch the ACID AI hackathon demo dashboard."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to bind the demo web dashboard (default: 5000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind (default: 127.0.0.1)",
    )
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        print(f"⚠️ Non-localhost host '{args.host}' disallowed for security. Enforcing 127.0.0.1.")
        args.host = "127.0.0.1"

    app = create_app()

    banner = rf"""
========================================================================
⚡  ACID AI — AI-Powered CI/CD Failure Diagnosis & Self-Healing  ⚡
========================================================================
   Subtitle:           Diagnose failures. Propose fixes. Verify safely.
   Host:               http://{args.host}:{args.port}
   API Scenarios:      http://{args.host}:{args.port}/api/scenarios
   System Status:      http://{args.host}:{args.port}/api/system-status
   Security Guard:     FAIL-CLOSED ISOLATION ENFORCED
========================================================================
   Press Ctrl+C to terminate the presentation server.
========================================================================
"""
    print(banner)

    try:
        app.run(host=args.host, port=args.port, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Demo server stopped cleanly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
