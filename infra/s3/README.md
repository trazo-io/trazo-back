# trazo-media bucket policy

`trazo-media-bucket-policy.json` is the policy production should carry: anonymous `s3:GetObject`
only under `backend.storage.PUBLIC_MEDIA_PREFIXES` (consumer-facing images). Every other key,
operator records included, is readable only through the app (signed, expiring URLs from
`backend.storage.private_records_storage`, or the authenticated download routes).

`backend/tests/test_private_records_storage.py` fails if this file and `PUBLIC_MEDIA_PREFIXES`
disagree, or if any statement grants the whole bucket.

Applying it is a manual, reviewed step (no Terraform manages this bucket):

    aws s3api put-bucket-policy --bucket trazo-media --policy file://infra/s3/trazo-media-bucket-policy.json

`trazo-media-bucket-policy.before-2026-10-01.json` is the policy it replaced (anonymous read of the
whole bucket), kept as the one-call rollback. Do not re-apply it except to roll back.

Versioning is on. Noncurrent versions need no cleanup: neither policy grants `s3:GetObjectVersion`.
