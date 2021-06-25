FROM python:3.9.5-slim-buster

RUN apt-get update

RUN apt-get install -y bluez bluetooth dbus


COPY dbus.conf /etc/dbus-1/session.d/


WORKDIR /usr/src/app

COPY . .

COPY setup.cfg ./

RUN pip install .


ENTRYPOINT [ "./entrypoint.sh" ]