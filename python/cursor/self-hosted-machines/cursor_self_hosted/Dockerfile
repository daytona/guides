FROM daytonaio/sandbox:0.6.0

USER root

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/* \
    && curl --fail --location --silent --show-error \
        https://downloads.cursor.com/lab/2026.09.02-e3e9343/linux/x64/agent-cli-package.tar.gz \
        --output /tmp/cursor-agent.tar.gz \
    && echo "a29694895b3b5d90e7d751eddfd2682e4872c9db6c2a3dee9eb3940a74d58c1cd498be3cc5ddf22bc7a22f2e8011e7430e5392149d1704ce952b368fa105d484  /tmp/cursor-agent.tar.gz" \
        | b2sum --check --status \
    && mkdir -p /opt/cursor-agent \
    && tar --extract --gzip --file /tmp/cursor-agent.tar.gz \
        --directory /opt/cursor-agent --strip-components=1 \
    && rm /tmp/cursor-agent.tar.gz \
    && ln -s /opt/cursor-agent/cursor-agent /usr/local/bin/agent \
    && ln -s /opt/cursor-agent/cursor-agent /usr/local/bin/cursor-agent \
    && agent --version \
    && mkdir -p /home/daytona/workspace \
    && chown daytona:daytona /home/daytona/workspace

USER daytona
WORKDIR /home/daytona/workspace
