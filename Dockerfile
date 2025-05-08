FROM python:3.11-alpine

ARG VERSION=dev
ARG BUILD_DATE
ARG VCS_REF

LABEL org.opencontainers.image.title="ESO Cluster Secret Store Per Namespace"
LABEL org.opencontainers.image.description="Kubernetes operator that creates ClusterSecretStore resources in namespaces with a specific label"
LABEL org.opencontainers.image.url="https://github.com/framjet/eso-cluster-secret-store-per-ns"
LABEL org.opencontainers.image.source="https://github.com/framjet/eso-cluster-secret-store-per-ns"
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.created=$BUILD_DATE
LABEL org.opencontainers.image.revision=$VCS_REF
LABEL org.opencontainers.image.vendor="FramJet"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY k8s_operator.py .

CMD ["python", "k8s_operator.py"] 