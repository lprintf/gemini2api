import os
import shutil
from datetime import datetime
from pathlib import Path

# 优先级：环境变量 DATA_DIR > 容器内路径 /app/data
DATA_DIR_STR = os.getenv("DATA_DIR", "/app/data")
DATA_DIR = Path(DATA_DIR_STR)

def clean():
    date_str = datetime.now().strftime("%Y%m%d")
    
    # 目标目录映射
    targets = {
        "Logs": DATA_DIR / "log" / date_str,
        "HTML Debug": DATA_DIR / "debug" / date_str
    }
    
    print(f"🧹 开始清理今日 ({date_str}) 的日志和 HTML 调试文件...")
    
    for name, target in targets.items():
        if target.exists():
            print(f"🗑️ 正在删除 {name}: {target}")
            try:
                # 删除整个日期目录以清除所有旧文件
                shutil.rmtree(target)
                # 重新创建空目录，确保业务代码（如 logger）在写入新日志时目录存在
                target.mkdir(parents=True, exist_ok=True)
                print(f"✅ {name} 清理完成")
            except Exception as e:
                print(f"❌ {name} 清理失败: {e}")
        else:
            print(f"ℹ️ {name} 目录不存在，无需清理: {target}")
            # 主动创建目录，防止业务代码因为目录缺失报错
            target.mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    clean()
