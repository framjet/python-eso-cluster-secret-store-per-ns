import kopf
import kubernetes
import yaml
import os
import logging
from kubernetes import client, config
from string import Template

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to load in-cluster config, fall back to kubeconfig
try:
    config.load_incluster_config()
    logger.info("Loaded in-cluster configuration")
except config.ConfigException:
    config.load_kube_config()
    logger.info("Loaded kubeconfig configuration")

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

logger.info(f"Operator configuration:")
logger.info(f"  TARGET_LABEL_KEY: {TARGET_LABEL_KEY}")
logger.info(f"  TARGET_LABEL_VALUE: {TARGET_LABEL_VALUE}")
logger.info(f"  PROCESS_EXISTING: {PROCESS_EXISTING}")
logger.info(f"  CLEANUP_ON_DELETE: {CLEANUP_ON_DELETE}")
logger.info(f"  NAME_PREFIX: {NAME_PREFIX}")

def get_template_from_configmap():
    """Get the template from ConfigMap."""
    namespace = os.environ.get('POD_NAMESPACE', 'default')
    template_name = os.environ.get('TEMPLATE_NAME', 'namespace-operator-template')
    
    logger.info(f"Reading template ConfigMap: {template_name} from namespace: {namespace}")

    try:
        configmap = v1.read_namespaced_config_map(
            name=template_name,
            namespace=namespace
        )
        template_content = configmap.data.get('template.yaml')
        if not template_content:
            logger.error(f"ConfigMap {template_name} exists but has no 'template.yaml' key")
            return None
        logger.info(f"Successfully loaded template from ConfigMap")
        return template_content
    except kubernetes.client.rest.ApiException as e:
        logger.error(f"Kubernetes API error reading template ConfigMap: {e.status} - {e.reason}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error reading template ConfigMap: {str(e)}")
        return None

@kopf.on.startup()
def startup(settings: kopf.OperatorSettings, **_):
    """Process existing namespaces on startup if enabled."""
    logger.info("Operator starting up...")

    settings.peering.standalone = True

    # Test template loading
    template = get_template_from_configmap()
    if not template:
        logger.error("Failed to load template - operator may not work correctly")
    else:
        logger.info("Template loaded successfully")

    if PROCESS_EXISTING:
        logger.info("Processing existing namespaces...")
        try:
            namespaces = v1.list_namespace()
            processed_count = 0
            for namespace in namespaces.items:
                labels = namespace.metadata.labels or {}
                if labels.get(TARGET_LABEL_KEY) == TARGET_LABEL_VALUE:
                    logger.info(f"Processing existing namespace: {namespace.metadata.name}")
                    create_cluster_secret_store(namespace.metadata.name, namespace.metadata)
                    processed_count += 1
            logger.info(f"Processed {processed_count} existing namespaces")
        except Exception as e:
            logger.error(f"Error processing existing namespaces: {str(e)}")
    else:
        logger.info("Skipping existing namespace processing (PROCESS_EXISTING=false)")

@kopf.on.cleanup()
def cleanup(**_):
    """Clean up ClusterSecretStore resources on operator deletion if enabled."""
    logger.info("Operator cleanup starting...")

    if CLEANUP_ON_DELETE:
        logger.info("Cleaning up ClusterSecretStore resources...")
        try:
            # List all ClusterSecretStore resources
            stores = custom_api.list_cluster_custom_object(
                group="external-secrets.io",
                version="v1",
                plural="clustersecretstores"
            )
            
            # Delete only resources created by our operator
            deleted_count = 0
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
                        logger.info(f"Deleted ClusterSecretStore: {name}")
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"Error deleting ClusterSecretStore {name}: {str(e)}")
            logger.info(f"Cleanup completed, deleted {deleted_count} ClusterSecretStores")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
    else:
        logger.info("Skipping cleanup (CLEANUP_ON_DELETE=false)")

@kopf.on.create('', 'v1', 'namespaces')
@kopf.on.update('', 'v1', 'namespaces')
def handle_namespace(spec, meta, **kwargs):
    """Handle namespace creation/update events."""
    namespace = meta['name']
    labels = meta.get('labels', {})
    
    logger.info(f"Handling namespace event for: {namespace}")
    logger.info(f"Namespace labels: {labels}")

    # Check if namespace has the required label with true value
    if labels.get(TARGET_LABEL_KEY) == TARGET_LABEL_VALUE:
        logger.info(f"Namespace {namespace} has target label, creating ClusterSecretStore")
        create_cluster_secret_store(namespace, meta)
    else:
        logger.info(f"Namespace {namespace} does not have target label, checking for cleanup")
        # If label is removed or changed, delete the ClusterSecretStore
        delete_cluster_secret_store(namespace)

@kopf.on.delete('', 'v1', 'namespaces')
def handle_namespace_delete(spec, meta, **kwargs):
    """Handle namespace deletion events."""
    namespace = meta['name']
    logger.info(f"Handling namespace deletion for: {namespace}")
    delete_cluster_secret_store(namespace)

def create_cluster_secret_store(namespace, meta):
    """Create a ClusterSecretStore for the given namespace."""
    logger.info(f"Creating ClusterSecretStore for namespace: {namespace}")

    template = get_template_from_configmap()
    if not template:
        logger.error(f"No template found for namespace: {namespace}")
        return

    # Replace placeholders in template
    template_str = Template(template)
    try:
        body_yaml = template_str.substitute(NAMESPACE=namespace)
        logger.info(f"Template substitution completed for namespace: {namespace}")
    except Exception as e:
        logger.error(f"Error substituting template for namespace {namespace}: {str(e)}")
        return
    
    try:
        body = yaml.safe_load(body_yaml)
        logger.info(f"Template YAML parsed successfully for namespace: {namespace}")

        # Add operator-specific label
        if 'metadata' not in body:
            body['metadata'] = {}
        if 'labels' not in body['metadata']:
            body['metadata']['labels'] = {}
        body['metadata']['labels'][OPERATOR_LABEL_KEY] = OPERATOR_LABEL_VALUE

        # Handle both dict (from kopf events) and V1ObjectMeta (from direct API calls)
        if hasattr(meta, 'labels') and meta.labels:
            # V1ObjectMeta object
            labels = meta.labels or {}
            uid = meta.uid
        else:
            # Dictionary from kopf event
            labels = meta.get('labels', {})
            uid = meta.get('uid')

        if labels.get("app.kubernetes.io/instance"):
            body['metadata']['labels']['app.kubernetes.io/instance'] = labels['app.kubernetes.io/instance']
        
        # Add owner reference to the namespace (FIXED)
        body['metadata']['ownerReferences'] = [{
            'apiVersion': 'v1',  # Fixed: was 'apps/v1'
            'kind': 'Namespace',
            'name': namespace,
            'uid': uid,
            'controller': True,
            'blockOwnerDeletion': True
        }]
        
        logger.info(f"Attempting to create ClusterSecretStore with name: {body['metadata']['name']}")

        custom_api.create_cluster_custom_object(
            group="external-secrets.io",
            version="v1",
            plural="clustersecretstores",
            body=body
        )
        logger.info(f"Successfully created ClusterSecretStore for namespace: {namespace}")
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error for namespace {namespace}: {str(e)}")
    except kubernetes.client.rest.ApiException as e:
        logger.error(f"Kubernetes API error creating ClusterSecretStore for namespace {namespace}: {e.status} - {e.reason}")
        if hasattr(e, 'body'):
            logger.error(f"API error details: {e.body}")
    except Exception as e:
        logger.error(f"Unexpected error creating ClusterSecretStore for namespace {namespace}: {str(e)}")

def delete_cluster_secret_store(namespace: str) -> None:
    """Delete a ClusterSecretStore for a namespace if it was created by our operator."""
    store_name = f"{NAME_PREFIX}{namespace}"
    logger.info(f"Attempting to delete ClusterSecretStore: {store_name}")

    try:
        # First check if the resource exists and was created by us
        try:
            store = custom_api.get_cluster_custom_object(
                group="external-secrets.io",
                version="v1",
                plural="clustersecretstores",
                name=store_name
            )
            
            # Only delete if it has our label
            labels = store.get('metadata', {}).get('labels', {})
            if labels.get(OPERATOR_LABEL_KEY) != OPERATOR_LABEL_VALUE:
                logger.info(f"Skipping deletion of ClusterSecretStore {store_name} as it was not created by this operator")
                return
                
        except kubernetes.client.rest.ApiException as e:
            if e.status == 404:
                logger.info(f"ClusterSecretStore {store_name} not found, skipping deletion")
                return
            raise

        # If we get here, the resource exists and was created by us, so delete it
        custom_api.delete_cluster_custom_object(
            group="external-secrets.io",
            version="v1",
            plural="clustersecretstores",
            name=store_name
        )
        logger.info(f"Successfully deleted ClusterSecretStore: {store_name}")
    except kubernetes.client.rest.ApiException as e:
        if e.status == 404:
            logger.info(f"ClusterSecretStore {store_name} not found during deletion, skipping")
        else:
            logger.error(f"Kubernetes API error deleting ClusterSecretStore {store_name}: {e.status} - {e.reason}")
    except Exception as e:
        logger.error(f"Unexpected error deleting ClusterSecretStore {store_name}: {str(e)}")

if __name__ == '__main__':
    logger.info("Starting kopf operator...")
    kopf.run(standalone=True)