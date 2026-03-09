from app.tasks.celery_app import celery_app

celery_app.conf.beat_schedule = {
    "close-expired-markets": {
        "task": "app.tasks.market_tasks.close_expired_markets",
        "schedule": 60.0,  # every 60 seconds
    },
}
