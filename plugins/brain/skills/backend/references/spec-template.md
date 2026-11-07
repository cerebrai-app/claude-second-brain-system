# Backend spec: <impl name>

Status: draft | approved <date> · Implementation: `<type>/<impl>` · Script: `python:<name>` · Spec version: 1

> Write this with the user. Every section is required; write "none" or "not supported" rather than leaving one empty. No secrets.

## 1. Purpose
What this backend is for, in two sentences. Which core type it stores. Who owns the data (the service is the source of truth).

## 2. Service and client
- Service and API (name, version, base URL pattern, link to the docs used):
- Client: official SDK `<package>` `<version constraint>` | plain HTTP via `<library>`:
- Region, workspace or account notes:

## 3. Authentication
| Environment variable | What it holds | Scopes or permissions needed |
|---|---|---|
| `EXAMPLE_API_TOKEN` | API token | read and write tasks in one project |

The values never appear in the repo, the spec, the registry or logs.

## 4. Scope and settings
| Setting | Meaning | Example |
|---|---|---|
| `project` | The service project or list this binding stores into | `"Q4"` |

## 5. Capabilities (what `describe` reports)
| Capability | Value | Why |
|---|---|---|
| `supports_body` | true / false | Where the markdown body lives in the service |
| `preserves_unknown_fields` | true / false | Can implementation-specific fields round-trip? |
| `supports_traits` | true / false | (person only) |
| `tags` | `map` / `labels` | If `labels`: the side field that holds the values (`storage.tag_values_field`): |
| `query` | keys honored natively | The rest are filtered by the caller |
| `max_page` | n | The service's maximum page size |
| `hard_delete` | true / false | |
| `native_ids` | true / false | |
| `archive_adapter` | false | Almost always false |
| `transactions` | false | |

## 6. Operations
| Operation | Supported | Service call(s) | Notes |
|---|---|---|---|
| `describe` | yes | none | |
| `create` | yes / no | | Conflict if the id exists |
| `read` | yes | | |
| `update` | yes / no | | Full replace; revision check: how? |
| `delete` | yes / no | | Needs `confirm: "permanent"` |
| `list` | yes | | Pagination: cursor or offset |
| `resolve` | yes | | |

**Revision.** Source (etag, version number, updated timestamp, content hash) and how `update` and `delete` check it. If the service has no compare-and-set, say so: update is best effort and may overwrite a concurrent change.

## 7. Id strategy
How the plugin's ULID `id` is stored in the service (custom field / description marker / label) or, if it cannot be, how the id index maps it (`native_ids: true`). How `read` and `resolve` find an item by `ref`.

## 8. Field mapping
| Envelope | Service | Notes |
|---|---|---|
| `fields.title` | `<service field>` | |
| `fields.status` | see section 9 | |
| `fields.tags` | `<labels or properties>` | Names and values; normalization |
| `body` | `<description or notes>` | Markdown handling; size limits |
| `created`, `updated` | `<timestamps>` | |
| `fields.<extra>` | `<service field>` | Type from the field type vocabulary; becomes `schema.fields` |

Fields the service has that the implementation does not map are ignored on read. Say whether they are preserved on update.

## 9. Status mapping
| Service state | Core status | Custom `status_values` entry |
|---|---|---|
| `Not started` | `open` | |
| `In progress` | `open` | `in_progress: open` |
| `Done` | `done` | |
| `Cancelled` | `dropped` | |

How `completed` is derived (the service's completion time, or none).

## 10. Relations
| Relation | Service concept | Supported |
|---|---|---|
| `belongs_to` | parent project / list | yes / no |
| `assigned_to` | assignee | yes / no (maps to a person ref how?) |
| `blocked_by` | dependency | yes / no |

Unsupported relations are dropped on write and absent on read; the user is told in this spec.

## 11. Query pushdown
Which of `types`, `impls`, `fields_eq`, `relations_include`, `updated_since`, `include_archived` the service filters natively, and how. Everything else is filtered by the caller.

## 12. Limits and errors
- Page size, rate limits, payload limits:
- Error mapping (service to adapter error): 401/403 `unauthorized`, 404 `not_found`, 409/412 `conflict`, 400/422 `invalid`, 429 `rate_limited` (`retry_after` from `<header>`), 5xx and timeouts `unavailable`:
- Anything that behaves unexpectedly:

## 13. Test plan
- Fake client behaviors that must match the service (list the ones that matter):
- Mapping cases covered:
- Sandbox for real-service verification (name, what may be created there):

## 14. Open questions
1.
