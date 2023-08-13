FROM python:3.11.4-bookworm

RUN apt-get update && apt-get install --no-install-recommends -y \
  sqlite3 \
  bluez \
  bluetooth \
  dbus

SHELL ["/bin/bash", "-c"]

WORKDIR /pyde1

ADD src ./src
ADD install ./install
ADD LICENSE .
ADD pyproject.toml .
ADD setup.cfg .
ADD entrypoint.sh .

ENV PYDE1_USER=pyde1
ENV PYDE1_GROUP="${PYDE1_USER}"
ENV PYDE1_ROOT=/pyde1/src/pyDE1
ENV VENV_PATH=/pyde1/venv
ARG BROKER_HOSTNAME=::1

# bypass the config file and use our own env vars defined above
RUN cat /dev/null > ./install/_config

RUN bash ./install/10-create-user.sh
RUN chsh -s $(which bash) $PYDE1_USER

RUN bash ./install/20-create-dirs.sh

RUN python3 -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"
RUN pip install setuptools .

RUN bash ./install/40-config-files.sh
RUN sed -i "s/\(\s\+BROKER_HOSTNAME: \).*/\1$BROKER_HOSTNAME/" /usr/local/etc/pyde1/pyde1.conf

CMD ["./entrypoint.sh"]
