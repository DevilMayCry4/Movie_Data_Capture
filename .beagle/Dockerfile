ARG BASE
FROM $BASE

LABEL maintainer="VergilGao"
LABEL build_from="https://github.com/DevilMayCry4/Movie_Data_Capture"
LABEL org.opencontainers.image.source="https://github.com/VergilGao/docker-mdc"

ENV TZ="Asia/Shanghai"
ENV UID=1000
ENV GID=1000
ENV UMASK=002

ADD .beagle/docker-entrypoint.sh docker-entrypoint.sh

RUN \
    apt-get -y update && apt-get -y upgrade \
    && apt install -y -q \
        gosu \
    && apt-get autoremove --purge -y \
    && apt-get clean -y \
    && chmod +x docker-entrypoint.sh \
    && mkdir -p /data /config \
    && useradd -d /config -s /bin/sh mdc \
    && chown -R mdc /data /config

COPY dist/Movie_Data_Capture /app

VOLUME [ "/data", "/config" ]

ENTRYPOINT ["/docker-entrypoint.sh"]

