import sys
import asyncio
from .launcher import GeminiLauncher

async def login(account_id: int):
    """启动浏览器进行登录"""
    launcher = GeminiLauncher(account_id=account_id)
    # 强制非无头模式
    page = await launcher.launch(headless=False)
    print(f"\n========================================")
    print(f"账户 {account_id} 浏览器已启动 (非无头模式)")
    print(f"请在窗口中完成登录操作。")
    print(f"完成后，直接在终端按 Ctrl+C 退出。")
    print(f"数据将自动保存到: {launcher.user_data_dir}")
    print(f"========================================\n")
    
    try:
        # 持续运行直到手动停止
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n正在关闭浏览器...")
    finally:
        await launcher.close()

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "login":
        acc_id = int(sys.argv[2])
        asyncio.run(login(acc_id))
    else:
        print("Usage: python -m server.services.automation login [account_id]")
