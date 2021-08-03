from apscheduler.schedulers.background import BackgroundScheduler
from backend.db import update_session

# References
# https://qiita.com/svfreerider/items/32ecd91d402b05fb8b9a
# https://www.pytry3g.com/entry/apscheduler


def job_update_session() -> None:
    """セッション更新ジョブ
    """
    # TODO: セッションが変更されたユーザのユーザ表現更新 (circular importをどう回避するか)
    update_session(change_limit_minutes=1)


def run_schedule() -> None:
    """定期実行ジョブのスケジューリング
    """
    sched = BackgroundScheduler(standalone=True, coalesce=True)
    sched.add_job(job_update_session, 'interval', minutes=1)    # セッション更新
    sched.start()
