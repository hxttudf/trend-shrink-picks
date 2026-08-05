#!/usr/bin/env python3
"""Helper to retry delivery of a pending WeChat message."""
import sys, os, asyncio

sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-agent"))

JOB_NAME = sys.argv[1] if len(sys.argv) > 1 else ""
CONTENT = sys.argv[2] if len(sys.argv) > 2 else ""

if not JOB_NAME or not CONTENT:
    print("Usage: _retry_delivery.py <job_name> <content>")
    sys.exit(1)

async def main():
    from gateway.platforms.weixin import check_weixin_requirements, send_weixin_direct
    from gateway.config import PlatformConfig

    if not check_weixin_requirements():
        print(f"[FAIL] {JOB_NAME}: Weixin requirements not met")
        sys.exit(1)

    wx_token = os.getenv("WEIXIN_TOKEN", "").strip()
    wx_account = os.getenv("WEIXIN_ACCOUNT_ID", "").strip()
    wx_home = os.getenv("WEIXIN_HOME_CHANNEL", "").strip()
    wx_base_url = os.getenv("WEIXIN_BASE_URL", "").strip()
    wx_cdn_base_url = os.getenv("WEIXIN_CDN_BASE_URL", "").strip()

    if not wx_token or not wx_account:
        print(f"[FAIL] {JOB_NAME}: WEIXIN_TOKEN or WEIXIN_ACCOUNT_ID not set")
        sys.exit(1)

    if not wx_home:
        wx_home = "filehelper"

    pconfig = PlatformConfig(
        enabled=True,
        token=wx_token,
        extra={
            "account_id": wx_account,
            "base_url": wx_base_url,
            "cdn_base_url": wx_cdn_base_url,
        },
    )

    result = await send_weixin_direct(
        extra=pconfig.extra,
        token=pconfig.token,
        chat_id=wx_home,
        message=CONTENT,
        media_files=[],
    )

    if isinstance(result, dict) and result.get("success"):
        print(f"[OK] {JOB_NAME}: Sent to WeChat (chat_id={wx_home})")
    elif isinstance(result, dict) and "error" in result:
        print(f"[FAIL] {JOB_NAME}: {result['error']}")
        sys.exit(1)
    else:
        print(f"[FAIL] {JOB_NAME}: Unexpected result: {result}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
