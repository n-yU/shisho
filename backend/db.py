from logging import getLogger, StreamHandler, DEBUG, Formatter
from typing import Dict, Union
import sys
from pathlib import Path
import random
import string
from datetime import datetime as dt
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.sql.functions import current_timestamp
from sqlalchemy import Column, String, Integer, create_engine, TIMESTAMP, text, ForeignKey, Boolean
from flask_login import UserMixin
from flask_bcrypt import Bcrypt

parent_dir = str(Path(__file__).parent.parent.resolve())
sys.path.append(parent_dir)
from config import get_config

# ロガー設定
logger = getLogger(__name__)
handler = StreamHandler()
handler.setLevel(DEBUG)
logger.setLevel(DEBUG)
logger.addHandler(handler)
logger.propagate = False
handler.setFormatter(Formatter('[shisho] %(message)s'))

DATABASE = 'mysql://{0}:{1}@{2}/{3}?charset=utf8mb4'.format(
    'test', 'test', 'mysql:3306', 'app')    # TODO: 環境変数から参照

ENGINE = create_engine(DATABASE, convert_unicode=True, echo=True)   # DBエンジン作成
session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=ENGINE))  # scoped_sessionによるセッション生成

Base = declarative_base()   # モデルベースクラス

# scoped_sessionではテーブル定義の継承元クラスにqueryプロパティを仕込む
# ref.) https://qiita.com/tosizo/items/86d3c60a4bb70eb1656e#scoped_session%E3%81%AB%E3%82%88%E3%82%8B%E7%94%9F%E6%88%90orm%E7%B7%A8
Base.query = session.query_property()


class User(Base):
    """ユーザテーブル
    """
    __tablename__ = 'users'  # テーブル名
    uId = Column('uId', String(100), primary_key=True, nullable=False)  # ユーザID
    sId = Column('sId', String(200), nullable=False)                    # セッションID
    name = Column('name', String(200), nullable=False)                  # ユーザ名
    password = Column('password', String(100), nullable=False)          # パスワード
    # 最終アクティブ（最後に書籍情報を閲覧した）時刻
    active_at = Column('active_at', TIMESTAMP, server_default=current_timestamp())
    changed_sId = Column('changed_sId', Boolean, default=True)                          # セッションID変更済フラグ
    created_at = Column('created_at', TIMESTAMP, server_default=current_timestamp())    # 作成時刻
    updated_at = Column('updated_at', TIMESTAMP, nullable=False,                        # 更新時刻
                        server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'))

    histories = relationship('History', backref='users')    # Historyとのリレーション


class History(Base):
    """閲覧履歴テーブル
    """
    __tablename__ = 'histories'  # テーブル名
    id = Column(Integer, primary_key=True)                      # ログID
    uId = Column('uId', String(100), ForeignKey('users.uId'))   # ユーザID（ユーザテーブルとの外部キー）
    sId = Column('sId', String(200), nullable=False)            # セッションID
    bId = Column('bId', String(200), nullable=False)            # 書籍ID
    ts = Column('ts', TIMESTAMP, nullable=False)                # タイムスタンプ
    isLast = Column('isLast', Boolean, default=False)           # セッション末尾書籍フラグ


class LoginUser(UserMixin, User):
    """ログイン機能用ユーザモデル
    """

    def get_id(self) -> str:
        """認証用ユーザID取得

        Returns:
            str:ユーザID
        """
        return self.uId


def get_sId(n=12) -> str:
    """セッションID生成

    Args:
        n (int, optional): 文字列サイズ. Defaults to 12.

    Returns:
        str: セッションID
    """
    # ref.) https://qiita.com/Scstechr/items/c3b2eb291f7c5b81902a
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def record_history(user: LoginUser, bId: str) -> None:
    """書籍閲覧履歴記録

    Args:
        user (LoginUser): ユーザ
        bId (str): 閲覧書籍ISBN-10
    """

    # 履歴記録
    cts = dt.now()  # 現在時刻
    log = History(uId=user.uId, sId=user.sId, bId=bId, ts=cts)
    session.add(log)

    # 最終アクティブ時刻更新
    target_user = User.query.get(user.uId)
    target_user.active_at = cts
    target_user.changed_sId = False  # AFK状態 -> 次回以降のセッション変更
    session.commit()

    # DEBUG:
    # for user in session.query(User).join(History, User.uId == History.uId).all():
    #     for log in user.histories:
    #         logger.debug('{0}:{1} -> {2} ({3}) ({4})'.format(log.uId, log.sId, log.bId, log.ts, log.isLast))


def get_user_history(user: LoginUser) -> Dict[int, Dict[int, Union[int, str, dt]]]:
    """書籍閲覧履歴取得

    Args:
        user (LoginUser): ユーザ

    Returns:
        Dict[int, Dict[int, Union[int, str, dt]]]: 閲覧履歴
    """

    raw_user_history = History.query.filter(History.uId == user.uId).all()

    # 変換: History -> Dict(key:lId)
    user_history = dict()
    for log in raw_user_history:
        user_history[log.id] = dict()
        user_history[log.id]['uId'] = log.uId
        user_history[log.id]['sId'] = log.sId
        user_history[log.id]['bId'] = log.bId
        user_history[log.id]['ts'] = log.ts

    return user_history


def change_session(user: LoginUser) -> None:
    """セッション変更

    Args:
        user (LoginUser): ログインユーザ
    """
    target_user = User.query.get(user.uId)
    target_user.sId = get_sId()  # セッションID変更
    target_user.changed_sId = True  # セッション変更済

    # セッション末尾ログフラグ設定
    last_log = session.query(History).filter(History.uId == user.uId).order_by(History.ts.desc()).first()
    last_log.isLast = True

    session.commit()


def update_session(change_limit_minutes: int) -> None:
    """セッション更新（変更有無確認）

    Args:
        change_limit_minutes (int): セッション変更上限時刻（現在時刻と最終アクティブ時刻の差）
    """
    cts = dt.now()              # 現在時刻
    users = User.query.all()    # 全ユーザ

    for user in users:
        if user.changed_sId:
            # セッション変更済 -> 再変更しない
            continue

        time_diff_minutes = (cts - user.active_at).seconds // 60    # 時間差（分単位）
        if time_diff_minutes >= change_limit_minutes:
            # 上限オーバー -> セッション変更
            change_session(user=user)


def main():
    """全テーブル初期化
    """
    config = get_config()   # 司書設定
    Base.metadata.drop_all(bind=ENGINE)     # 全テーブル削除
    Base.metadata.create_all(bind=ENGINE)   # 全テーブル作成

    # 管理者アカウント作成
    admin_user = LoginUser(uId=config['admin_user_id'], sId=get_sId(), name=config['admin_user_name'],
                           password=Bcrypt().generate_password_hash(config['admin_user_password']).decode('utf-8'))
    session.add(admin_user)    # INSERT: 管理者アカウント
    session.commit()        # テーブル更新


if __name__ == "__main__":
    main()
