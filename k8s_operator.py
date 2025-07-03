import kopf
import kubernetes
import yaml
import os
from kubernetes import client, config
from string import Template

# Try to load in-cluster config, fall back to kubeconfig
try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

v1 = client.CoreV1Api()
custom_api = client.CustomObjectsApi()

CLUSTER_SECRET_STORE_API_VERSION = "external-secrets.io/v1"
CLUSTER_SECRET_STORE_KIND = "ClusterSecretStore"

# Get configuration from environment variables
TARGET_LABEL_KEY = os.environ.get('TARGET_LABEL_KEY', 'k8s.framjet.dev/eso-cluster-secret-store-per-ns')
TARGET_LABEL_VALUE = os.environ.get('TARGET_LABEL_VALUE', 'true')
PROCESS_EXISTING = os.environ.get('PROCESS_EXISTING', 'true').lower() == 'true'
CLEANUP_ON_DELETE = os.environ.get('CLEANUP_ON_DELETE', 'true').lower() == 'true'
NAME_PREFIX = os.environ.get('CLUSTER_SECRET_STORE_NAME_PREFIX', 'k8s-')
OPERATOR_LABEL_KEY = 'k8s.framjet.dev/managed-by'
OPERATOR_LABEL_VALUE = 'eso-cluster-secret-store-per-ns'

def get_template_from_configmap():
    """Get the template from ConfigMap."""
    namespace = os.environ.get('POD_NAMESPACE', 'default')
    template_name = os.environ.get('TEMPLATE_NAME', 'namespace-operator-template')
    
    try:
        configmap = v1.read_namespaced_config_map(
            name=template_name,
            namespace=namespace
        )
        return configmap.data['template.yaml']
    except Exception as e:
        print(f"Error reading template ConfigMap: {str(e)}")
        return None

@kopf.on.startup()
def startup(**_):
    """Process existing namespaces on startup if enabled."""
    if PROCESS_EXISTING:
        print("Processing existing namespaces...")
        namespaces = v1.list_namespace()
        for namespace in namespaces.items:
            labels = namespace.metadata.labels or {}
            if labels.get(TARGET_LABEL_KEY) == TARGET_LABEL_VALUE:
                print(f"Processing existing namespace: {namespace.metadata.name}")
                create_cluster_secret_store(namespace.metadata.name, namespace.metadata)

@kopf.on.cleanup()
def cleanup(**_):
    """Clean up ClusterSecretStore resources on operator deletion if enabled."""
    if CLEANUP_ON_DELETE:
        print("Cleaning up ClusterSecretStore resources...")
        try:
            # List all ClusterSecretStore resources
            stores = custom_api.list_cluster_custom_object(
                group="external-secrets.io",
                version="v1",
                plural="clustersecretstores"
            )
            
            # Delete only resources created by our operator
            for store in stores.get('items', []):
                labels = store.get('metadata', {}).get('labels', {})
                if labels.get(OPERATOR_LABEL_KEY) == OPERATOR_LABEL_VALUE:
                    name = store['metadata']['name']
                    try:
                        custom_api.delete_cluster_custom_object(
                            group="external-secrets.io",
                            version="v1",
                            plural="clustersecretstores",
                            name=name
                        )
                        print(f"Deleted ClusterSecretStore: {name}")
                    except Exception as e:
                        print(f"Error deleting ClusterSecretStore {name}: {str(e)}")
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")

@kopf.on.create('', 'v1', 'namespaces')
@kopf.on.update('', 'v1', 'namespaces')
def handle_namespace(spec, meta, **kwargs):
    """Handle namespace creation/update events."""
    namespace = meta['name']
    labels = meta.get('labels', {})
    
    # Check if namespace has the required label with true value
    if labels.get(TARGET_LABEL_KEY) == TARGET_LABEL_VALUE:
        create_cluster_secret_store(namespace, meta)
    else:
        # If label is removed or changed, delete the ClusterSecretStore
        delete_cluster_secret_store(namespace)

def create_cluster_secret_store(namespace, meta):
    """Create a ClusterSecretStore for the given namespace."""
    template = get_template_from_configmap()
    if not template:
        print(f"No template found for namespace: {namespace}")
        return

    # Replace placeholders in template
    template_str = Template(template)
    body_yaml = template_str.substitute(NAMESPACE=namespace)
    
    try:
        body = yaml.safe_load(body_yaml)
        
        # Add operator-specific label
        if 'metadata' not in body:
            body['metadata'] = {}
        if 'labels' not in body['metadata']:
            body['metadata']['labels'] = {}
        body['metadata']['labels'][OPERATOR_LABEL_KEY] = OPERATOR_LABEL_VALUE

        labels = meta.get('labels', {})
        if labels.get("app.kubernetes.io/instance"):
            body['metadata']['labels']['app.kubernetes.io/instance'] = labels['app.kubernetes.io/instance']
        
        # Add owner reference to the operator
        body['metadata']['ownerReferences'] = [{
            'apiVersion': 'apps/v1',
            'kind': 'Namespace',
            'name': namespace,
            'uid': meta['uid'],
            'controller': True,
            'blockOwnerDeletion': True
        }]
        
        custom_api.create_cluster_custom_object(
            group="external-secrets.io",
            version="v1",
            plural="clustersecretstores",
            body=body
        )
        print(f"Created ClusterSecretStore for namespace: {namespace}")
    except Exception as e:
        print(f"Error creating ClusterSecretStore for namespace {namespace}: {str(e)}")

def delete_cluster_secret_store(namespace: str) -> None:
    """Delete a ClusterSecretStore for a namespace if it was created by our operator."""
    try:
        # First check if the resource exists and was created by us
        try:
            store = custom_api.get_cluster_custom_object(
                group="external-secrets.io",
                version="v1",
                plural="clustersecretstores",
                name=f"{NAME_PREFIX}{namespace}"
            )
            
            # Only delete if it has our label
            labels = store.get('metadata', {}).get('labels', {})
            if labels.get(OPERATOR_LABEL_KEY) != OPERATOR_LABEL_VALUE:
                print(f"Skipping deletion of ClusterSecretStore for namespace {namespace} as it was not created by this operator")
                return
                
        except kubernetes.client.rest.ApiException as e:
            if e.status == 404:
                print(f"ClusterSecretStore for namespace {namespace} not found, skipping deletion")
                return
            raise

        # If we get here, the resource exists and was created by us, so delete it
        custom_api.delete_cluster_custom_object(
            group="external-secrets.io",
            version="v1",
            plural="clustersecretstores",
            name=f"{NAME_PREFIX}{namespace}"
        )
        print(f"Deleted ClusterSecretStore for namespace: {namespace}")
    except kubernetes.client.rest.ApiException as e:
        if e.status == 404:
            # Resource doesn't exist, which is fine
            print(f"ClusterSecretStore for namespace {namespace} not found, skipping deletion")
        else:
            # Re-raise if it's a different error
            raise

if __name__ == '__main__':
    kopf.run() 