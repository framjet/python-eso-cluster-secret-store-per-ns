# ESO Cluster Secret Store Per Namespace

A Kubernetes operator that automatically creates ClusterSecretStore resources for namespaces with a specific label.

## Prerequisites

- Kubernetes cluster
- External Secrets Operator installed
- Helm 3.x

## Installation

1. Add the Helm repository:
```bash
helm repo add framjet https://framjet.github.io/helm-charts
```

2. Install using Helm:
```bash
helm install eso-cluster-secret-store-per-ns framjet/eso-cluster-secret-store-per-ns
```

## Usage

To create a ClusterSecretStore for a namespace, add the label to the namespace:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: my-namespace
  labels:
    k8s.framjet.dev/eso-cluster-secret-store-per-ns: "true"
```

The operator will automatically create a ClusterSecretStore resource using the template from the ConfigMap.

## Configuration

The operator can be configured through Helm values:

```yaml
image:
  repository: framjet/eso-cluster-secret-store-per-ns
  tag: latest
  pullPolicy: IfNotPresent

serviceAccount:
  create: true
  name: namespace-operator
  annotations: {}

rbac:
  create: true

resources:
  limits:
    cpu: 100m
    memory: 128Mi
  requests:
    cpu: 50m
    memory: 64Mi

clusterSecretStore:
  # Enable/disable the default template ConfigMap
  create: true
  # Name of the template ConfigMap (defaults to <release-name>-template if not specified)
  name: ""
  # Default template configuration
  template:
    caProvider:
      type: ConfigMap
      name: kube-root-ca.crt
      key: ca.crt
      namespace: external-secrets
    auth:
      serviceAccount:
        name: external-secrets
        namespace: external-secrets

# Label configuration for namespace detection
label:
  # The label key to watch for
  key: "k8s.framjet.dev/eso-cluster-secret-store-per-ns"
  # The label value that triggers ClusterSecretStore creation
  value: "true"

# Cleanup configuration
cleanup:
  # Whether to delete ClusterSecretStore resources when the operator is deleted
  onDelete: true
  # Whether to process existing namespaces on operator startup
  processExisting: true
```

### Using Custom Templates

You can provide your own template by creating a ConfigMap with the following structure:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-custom-template
data:
  template.yaml: |
    apiVersion: external-secrets.io/v1beta1
    kind: ClusterSecretStore
    metadata:
      name: k8s-${NAMESPACE}
    spec:
      provider:
        kubernetes:
          remoteNamespace: ${NAMESPACE}
          # Your custom configuration here
```

Then set `clusterSecretStore.name: "my-custom-template"` in your Helm values.

The template can use the following variables:
- `${NAMESPACE}`: The namespace name

### Features

1. **Configurable Label**: You can change the label key and value that triggers ClusterSecretStore creation.

2. **Existing Namespace Processing**: By default, the operator will process all existing namespaces on startup that have the configured label.

3. **Automatic Cleanup**: When the operator is deleted, it can automatically clean up all ClusterSecretStore resources it created.

4. **Owner References**: All created ClusterSecretStore resources are owned by the operator deployment, ensuring proper cleanup.

## Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run locally:
```bash
python k8s_operator.py
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details. 