# Terraform (MVP)

This provisions cloud resources only. You still need to build/push container images.

## Apply

1. Create a `terraform.tfvars`:

```hcl
project_id       = "your-project"
region           = "us-central1"
prefix           = "investing-agent"
gcs_bucket_name  = "globally-unique-bucket-name"
db_password      = "change-me"
api_image        = "us-docker.pkg.dev/your-project/your-repo/api:latest"
worker_image     = "us-docker.pkg.dev/your-project/your-repo/worker:latest"
aggregator_image = "us-docker.pkg.dev/your-project/your-repo/aggregator:latest"
```

2. Run:

```bash
terraform init
terraform apply
```

## Security note

This MVP uses public Cloud Run ingress for the API (so your dashboard can call it). Before going multi-user, lock this down behind auth and restrict invokers.

