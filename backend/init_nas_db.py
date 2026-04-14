#!/usr/bin/env python3
"""
初始化NAS数据库脚本
用于在家庭NAS的MySQL中创建量化交易系统的表结构
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from app.core.nas_config import check_nas_connection, init_nas_database

def main():
    """主函数"""
    print("🔍 检查NAS数据库连接...")
    
    # 检查连接
    status = check_nas_connection()
    
    print("\n📊 连接状态:")
    print(f"  MySQL: {'✅ 连接成功' if status['mysql']['connected'] else '❌ 连接失败'}")
    if status['mysql']['connected']:
        print(f"    版本: {status['mysql'].get('version', 'unknown')}")
    else:
        print(f"    错误: {status['mysql'].get('error', 'Unknown error')}")
    
    print(f"  Redis: {'✅ 连接成功' if status['redis']['connected'] else '❌ 连接失败'}")
    if status['redis']['connected']:
        print(f"    版本: {status['redis'].get('version', 'unknown')}")
    else:
        print(f"    错误: {status['redis'].get('error', 'Unknown error')}")
    
    # 如果MySQL连接成功，进行初始化
    if status['mysql']['connected']:
        print("\n🔧 正在初始化NAS数据库表结构...")
        try:
            init_nas_database()
            print("✅ NAS数据库初始化完成！")
        except Exception as e:
            print(f"❌ 初始化失败: {str(e)}")
            sys.exit(1)
    else:
        print("\n❌ MySQL连接失败，无法初始化数据库")
        sys.exit(1)

if __name__ == "__main__":
    main()