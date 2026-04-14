import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app.services.morning.morning_brief_service import EnhancedMorningBriefService
    print("✅ 导入成功")
except Exception as e:
    print("❌ 导入失败:")
    traceback.print_exc()