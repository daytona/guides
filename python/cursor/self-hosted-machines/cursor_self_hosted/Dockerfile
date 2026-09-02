FROM daytonaio/sandbox:0.6.0

USER root

COPY --chown=root:root --chmod=0755 clone_repos.py /usr/local/bin/clone-cursor-self-hosted-repos

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/* \
    && curl --fail --location --silent --show-error \
        https://downloads.cursor.com/lab/2026.08.25-3e8eec8/linux/x64/agent-cli-package.tar.gz \
        --output /tmp/cursor-agent.tar.gz \
    && echo "cd5485f7524688e1a688daa2b64669c76bedcdd9ab87638bac78f9b42c2442bd5000559920a2f5171e00b5eb7fcf737f9111ef296f1eba40369cebf3279ee0a9  /tmp/cursor-agent.tar.gz" \
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
