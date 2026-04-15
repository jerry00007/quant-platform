#!/usr/bin/env python3
"""
测试增强版晨报服务
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from loguru import logger

from app.services.morning.morning_brief_service import EnhancedMorningBriefService

# 配置日志
logger.remove()
logger.add(sys.stderr, level="INFO")

def load_tushare_token():
    """从.env文件加载Tushare Token"""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("TUSHARE_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    if token and not token.startswith("#"):
                        return token
    return None

def test_morning_brief():
    """测试晨报服务"""
    try:
        # 创建SQLite数据库连接（使用现有数据库）
        db_path = os.path.join(os.path.dirname(__file__), "quantweave.db")
        engine = create_engine(f"sqlite:///{db_path}")
        Session = sessionmaker(bind=engine)
        db = Session()
        
        logger.info("🔧 初始化晨报服务...")
        
        # 加载Tushare token
        token = load_tushare_token()
        if token:
            logger.info(f"📝 使用Tushare Token (前4位): {token[:4]}...")
        else:
            logger.warning("⚠️ 未找到Tushare Token，部分功能可能受限")
        
        # 初始化服务
        service = EnhancedMorningBriefService(db, tushare_token=token)
        
        logger.info("📝 测试快速晨报...")
        quick_brief = service.generate_quick_brief(account_name="main")
        logger.success("快速晨报生成成功:")
        print("\n" + "="*60)
        print(quick_brief)
        print("="*60)
        
        logger.info("📋 测试全面晨报...")
        try:
            comprehensive_result = service.generate_comprehensive_brief(account_name="main")
            if comprehensive_result["success"]:
                logger.success("全面晨报生成成功")
                brief = comprehensive_result["brief"]
                print("\n" + "="*60)
                print(brief)
                print("="*60)
                
                # 打印数据摘要
                summary = comprehensive_result["data_summary"]
                logger.info(f"数据源: {summary['data_sources']}")
                logger.info(f"数据点: {summary['data_points']}")
            else:
                logger.warning(f"晨报生成失败: {comprehensive_result.get('error', '未知错误')}")
                print("\n" + comprehensive_result.get("fallback_brief", "无降级晨报"))
        except Exception as e:
            logger.error(f"全面晨报异常: {e}")
            import traceback
            traceback.print_exc()
        
        db.close()
        logger.info("✅ 测试完成")
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(test_morning_brief())