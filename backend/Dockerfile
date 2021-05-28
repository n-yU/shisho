FROM python:3.8.8

USER root
RUN apt-get update && apt-get -y install locales && \
    localedef -f UTF-8 -i ja_JP ja_JP.UTF-8

# MeCabなどのインストール
RUN apt-get install -y \
    make \
    curl \
    file \
    git \
    libmecab-dev \
    sudo \
    mecab \
    mecab-ipadic-utf8

# ロケール設定
ENV LANG ja_JP.UTF-8
ENV LANGUAGE ja_JP:ja
ENV LC_ALL ja_JP.UTF-8
ENV TZ JST-9

# flaskのポートのエクスポート等
EXPOSE 5000
ARG project_dir=/projects/
ENV HOME $project_dir
ENV PYTHONPATH $project_dir
ENV FLASK_APP $project_dir/app.py

# NEologdのインストール
RUN git clone --depth 1 https://github.com/neologd/mecab-ipadic-neologd.git
RUN mecab-ipadic-neologd/bin/install-mecab-ipadic-neologd -y

# 各Pythonライブラリインストール
COPY . $project_dir
WORKDIR $project_dir
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
