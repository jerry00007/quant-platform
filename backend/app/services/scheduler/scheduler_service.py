"""
QuantWeave - 定时任务调度器
支持：每日数据同步、策略信号扫描、风控巡检
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from datetime import datetime
from typing import Callable, Dict


class SchedulerService:
    """定时任务调度"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.jobs: Dict[str, dict] = {}

    def start(self):
        """启动调度器"""
        self.scheduler.start()
        logger.info("调度器已启动")

    def stop(self):
        """停止调度器"""
        self.scheduler.shutdown()
        logger.info("调度器已停止")

    def add_job(self, job_id: str, func: Callable, cron: str = "", 
                description: str = "", **kwargs):
        """
        添加定时任务
        cron 格式: "0 9 * * 1-5"（工作日每天9点）
        """
        parts = cron.split() if cron else []
        trigger_kwargs = {}
        if len(parts) >= 1:
            trigger_kwargs["minute"] = parts[0]
        if len(parts) >= 2:
            trigger_kwargs["hour"] = parts[1]
        if len(parts) >= 3:
            trigger_kwargs["day"] = parts[2]
        if len(parts) >= 4:
            trigger_kwargs["month"] = parts[3]
        if len(parts) >= 5:
            trigger_kwargs["day_of_week"] = parts[4]

        trigger = CronTrigger(**trigger_kwargs) if trigger_kwargs else None

        if trigger:
            job = self.scheduler.add_job(func, trigger=trigger, id=job_id, kwargs=kwargs)
        else:
            job = self.scheduler.add_job(func, "interval", minutes=30, id=job_id, kwargs=kwargs)

        self.jobs[job_id] = {
            "id": job_id,
            "description": description,
            "cron": cron,
            "next_run": str(job.next_run_time) if hasattr(job, "next_run_time") else "",
            "status": "running",
        }
        logger.info(f"添加任务: {job_id} | {description} | cron={cron}")

    def remove_job(self, job_id: str):
        """移除任务"""
        try:
            self.scheduler.remove_job(job_id)
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = "stopped"
            logger.info(f"移除任务: {job_id}")
        except Exception as e:
            logger.warning(f"移除任务失败 {job_id}: {e}")

    def pause_job(self, job_id: str):
        """暂停任务"""
        try:
            self.scheduler.pause_job(job_id)
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = "paused"
        except Exception as e:
            logger.warning(f"暂停任务失败 {job_id}: {e}")

    def resume_job(self, job_id: str):
        """恢复任务"""
        try:
            self.scheduler.resume_job(job_id)
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = "running"
        except Exception as e:
            logger.warning(f"恢复任务失败 {job_id}: {e}")

    def get_jobs(self) -> list:
        """获取所有任务状态"""
        result = []
        for job_id, info in self.jobs.items():
            try:
                job = self.scheduler.get_job(job_id)
                if job:
                    info["next_run"] = str(job.next_run_time)
                    info["status"] = "running"
            except Exception:
                pass
            result.append(info)
        return result

    def register_default_jobs(self, data_sync_func, signal_scan_func, risk_check_func,
                              morning_brief_func=None):
        """注册默认定时任务"""
        # 每个交易日 9:15 同步数据
        self.add_job("daily_sync", data_sync_func,
                     cron="15 9 * * 1-5",
                     description="每日行情数据同步")
        # 每个交易日 9:30 早盘提醒
        if morning_brief_func:
            self.add_job("morning_brief", morning_brief_func,
                         cron="30 9 * * 1-5",
                         description="9:30 早盘操作提醒")
        # 每个交易日 15:05 策略信号扫描
        self.add_job("signal_scan", signal_scan_func,
                     cron="5 15 * * 1-5",
                     description="策略信号扫描")
        # 每30分钟风控巡检
        self.add_job("risk_check", risk_check_func,
                     cron="*/30 9-15 * * 1-5",
                     description="风控巡检")
