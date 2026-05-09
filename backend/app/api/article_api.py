from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.database import get_db, SessionLocal
from ..services.article.article_service import ArticleService

router = APIRouter(prefix="/article", tags=["公众号文章"])


@router.get("/preview", summary="获取最新选股数据摘要")
def get_article_preview(db: Session = Depends(get_db)):
    svc = ArticleService(db)
    return svc.get_preview()


@router.post("/generate", summary="生成公众号文章")
def generate_article(db: Session = Depends(get_db)):
    svc = ArticleService(db)
    return svc.generate()


@router.get("/history", summary="获取历史文章列表")
def get_article_history():
    db = SessionLocal()
    try:
        svc = ArticleService(db)
        return {"items": svc.get_history()}
    finally:
        db.close()
