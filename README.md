# Jira Issue Synchronization Tool

A Python tool for synchronizing Jira issues between two Jira instances (Source and Target). This tool supports bidirectional synchronization of issue fields, attachments, and metadata.

## Features

- **Bidirectional Field Synchronization**: Sync fields from Source to Target (S2T) or Target to Source (T2S)
- **Multiple Sync Strategies**: 
  - `DIRECT_COPY`: Directly copy field values
  - `MAPPED_SYNC`: Map values using predefined mappings
  - `STATIC_VALUE`: Set static values on create/update
  - `SYNC_METADATA`: Track sync metadata (customer issue ID, last sync time)
- **Attachment Synchronization**: MERGE strategy ensures both sides have complete attachment union
- **ADF Format Support**: Handles Atlassian Document Format (ADF) for description and comment fields
- **Prefix Support**: Add prefixes to field values (e.g., `[MB-EAL]` to summary)
- **Multiple Authentication Methods**: Supports Basic Auth and Bearer Token
- **Smart Update Logic**: Uses last sync time to determine sync direction and avoid unnecessary updates
- **Skip No-Op Updates for Simple Fields**: For simple types (text/string, number, single-select option), the tool compares the new value with the current target value and skips the update if they are identical, reducing unnecessary API calls and churn

## Requirements

- Python 3.7+
- Required packages:
  - `requests`
  - `json` (built-in)
  - `base64` (built-in)
  - `datetime` (built-in)

## Configuration Files

### 1. `jira_config.json`

This file contains the configuration for Source and Target Jira instances.

#### Structure

```json
{
  "source": {
    "name": "Source Jira Name",
    "cloudId": "cloud-id-for-bearer-auth",
    "domain": "https://your-domain.atlassian.net/",
    "email": "your-email@example.com",
    "apiToken": "your-api-token",
    "projectKey": "PROJECT",
    "authType": "Basic",
    "note": "Optional note"
  },
  "target": {
    "name": "Target Jira Name",
    "cloudId": "cloud-id-for-bearer-auth",
    "apiToken": "your-api-token",
    "projectKey": "PROJECT",
    "authType": "Bearer",
    "note": "Optional note"
  },
  "syncIssueType": ["Bug", "Task"]
}
```

#### Configuration Fields

**Source/Target Configuration:**

- `name` (string): Display name for the Jira instance
- `cloudId` (string, required for Bearer auth): Cloud ID for Atlassian Cloud instances
- `domain` (string, required for Basic auth): Jira domain URL (e.g., `https://your-domain.atlassian.net/`)
- `email` (string, required for Basic auth): Email address for Basic authentication
- `apiToken` (string, required): Jira API token
- `projectKey` (string, required): Project key to sync issues from/to
- `authType` (string, required): Authentication type - `"Basic"` or `"Bearer"`
- `note` (string, optional): Optional note about the configuration

**Global Configuration:**

- `syncIssueType` (array of strings, optional): List of issue types to sync. If not specified, all issue types will be synced.

#### Authentication Types

**Basic Auth:**
- Requires: `domain`, `email`, `apiToken`
- Used for: Jira Server/Data Center or Atlassian Cloud with Basic auth

**Bearer Auth:**
- Requires: `cloudId`, `apiToken`
- Used for: Atlassian Cloud with OAuth 2.0

### 2. `jira_field_mapping.json`

This file defines how fields are mapped and synchronized between Source and Target Jira instances.

#### Structure

```json
[
  {
    "type": "system",
    "fieldId": "summary",
    "syncDirection": "S2T",
    "strategy": "DIRECT_COPY",
    "prefix": "[MB-EAL]",
    "note": "Add prefix to indicate bug is coming from customer"
  },
  {
    "type": "custom",
    "description": "Description -> Description_Bug",
    "sourceFieldId": "description",
    "targetFieldId": "customfield_10262",
    "syncDirection": "S2T",
    "strategy": "DIRECT_COPY",
    "prefix": "[STARC@Jira]"
  }
]
```

#### Field Mapping Properties

**Common Properties:**

- `type` (string, required): Field type - `"system"` or `"custom"`
- `syncDirection` (string, required): Sync direction - `"S2T"` (Source to Target), `"T2S"` (Target to Source), or `"BIDIRECTIONAL"`
- `strategy` (string, required): Sync strategy - `"DIRECT_COPY"`, `"MAPPED_SYNC"`, `"STATIC_VALUE"`, or `"SYNC_METADATA"`
- `prefix` (string, optional): Prefix to add to field values (only for S2T direction)
- `note` (string, optional): Optional note about the mapping

**System Fields:**

- `fieldId` (string, required): System field ID (e.g., `"summary"`, `"description"`, `"priority"`, `"status"`)

**Custom Fields:**

- `sourceFieldId` (string, required): Source custom field ID (e.g., `"customfield_10037"`)
- `targetFieldId` (string, required): Target custom field ID (e.g., `"customfield_10229"`)
- `targetFieldDataType` (string, optional): Target field data type (e.g., `"option"`, `"string"`, `"date"`)

**Strategy-Specific Properties:**

**MAPPED_SYNC:**
- `valueMapping` (object, required): Mapping from source values to target values
  ```json
  "valueMapping": {
    "High": "High",
    "Medium": "Medium",
    "Low": "Low"
  }
  ```
- `reverseMapping` (object, optional): Explicit reverse mapping for bidirectional sync
  ```json
  "reverseMapping": {
    "PLANNED": "IMPLEMENTING",
    "BLOCKED": "IMPLEMENTING"
  }
  ```

**STATIC_VALUE:**
- `static_value` or `staticValue` (object/string, required): Static value to set
  ```json
  "static_value": {
    "value": "Customer"
  }
  ```
- `trigger_on` or `triggerOn` (array, optional): When to apply - `["CREATE"]`, `["UPDATE"]`, or `["CREATE", "UPDATE"]` (default)

**SYNC_METADATA:**
- `metadataType` (string, required): Type of metadata - `"customer_issue_id"` or `"last_sync_time"`
  - `customer_issue_id`: Stores the source issue key for tracking
  - `last_sync_time`: Stores the timestamp of last sync operation

#### Sync Strategies

1. **DIRECT_COPY**: Directly copy the field value from source to target
2. **MAPPED_SYNC**: Map values using `valueMapping` dictionary. Supports bidirectional sync with `reverseMapping`
3. **STATIC_VALUE**: Set a static value when creating or updating issues
4. **SYNC_METADATA**: Automatically manage sync metadata:
   - `customer_issue_id`: Stores source issue key in target issue
   - `last_sync_time`: Tracks when the last sync occurred

**Value comparison for simple fields:** For simple types (text/string, number, single-select option), the tool compares the candidate new value with the current value on the target side and skips the update if they are identical. Complex types (multi-select, objects, ADF, attachments) are still updated directly.

#### Sync Directions

- **S2T** (Source to Target): Only sync from source to target
- **T2S** (Target to Source): Only sync from target to source
- **BIDIRECTIONAL**: Sync in both directions based on update timestamps

## Usage

### Basic Usage

1. **Configure Jira instances** in `jira_config.json`
2. **Define field mappings** in `jira_field_mapping.json`
3. **Run the script**:
   ```bash
   python sync_issues.py
   ```

### Debug Mode

The script includes a debug mode for testing. Set `DEBUG_MODE = True` in `sync_issues.py`:

```python
DEBUG_MODE = True
```

When enabled:
- Uses "Test" issue type to query Source Issues
- Uses "Bug" issue type to create Target Issues
- Only processes issue key `[projectkey]-27979`

### How It Works

1. **Connection Test**: Tests connection to both Source and Target Jira instances
2. **Get Source Issues**: Queries Source Jira for issues matching the configured issue types
3. **Get Target Issues**: Queries Target Jira for issues that have been synced (based on `customer_issue_id` field)
4. **Build Lookup Map**: Creates a map of target issues using `customer_issue_id` as key
5. **Synchronize**:
   - **Create**: If source issue doesn't exist in target, create new target issue
   - **Update**: If source issue exists in target, update based on sync direction and timestamps
   - **Attachments**: Always sync attachments using MERGE strategy (ensures both sides have complete union)

### Sync Logic

**Create Flow:**
1. Create target issue with mapped fields
2. Update metadata fields (customer_issue_id, last_sync_time)
3. Update static value fields
4. Sync attachments from source to target

**Update Flow:**
1. Compare `updated` timestamps of source and target issues
2. Use `last_sync_time` to determine if update is needed
3. Determine sync direction (S2T or T2S) based on timestamps
4. Update fields in the determined direction
5. Sync attachments bidirectionally (MERGE strategy)

### Attachment Synchronization

Attachments are synchronized using a **MERGE strategy**:
- Downloads all attachments from both source and target to local directory
- Uploads missing attachments from source to target (with `[SOURCE_PROJECT_KEY]` prefix)
- Uploads missing attachments from target to source (with `[TARGET_PROJECT_KEY]` prefix)
- Ensures both sides have the complete union of all attachments

Local attachments are stored in directories named after the target issue key.

## Field Prefix Support

You can add prefixes to field values using the `prefix` property in field mappings:

```json
{
  "type": "system",
  "fieldId": "summary",
  "prefix": "[MB-EAL]"
}
```

**Features:**
- Supports all S2T direction fields
- Automatically handles ADF format fields (description, comments)
- Prevents duplicate prefixes
- Format: `{prefix} {value}`

## ADF Format Handling

The tool automatically handles Atlassian Document Format (ADF) for fields like `description` and `comment.body`:
- Converts ADF to text when adding prefixes
- Preserves ADF structure when possible
- Falls back to original ADF if prefix addition fails

## Error Handling

The tool provides detailed error messages for:
- HTTP 401: Authentication failed
- HTTP 403: Insufficient permissions
- HTTP 404: Resource not found
- HTTP 410: Resource permanently removed
- Field update failures with detailed error information

## Notes

- **Attachment Field**: The attachment field mapping in `jira_field_mapping.json` is not required. Attachments are handled automatically by the `sync_attachments` function.
- **Issue Type**: Default issue type for new issues is "Bug" if not specified in source issue.
- **Last Sync Time**: Used to optimize updates - if both issues haven't changed since last sync, field updates are skipped (attachments still sync).

## Example Configuration

See `jira_config.json` and `jira_field_mapping.json` in the repository for complete examples.

## Troubleshooting

1. **Connection Failed**: Check API tokens and authentication settings
2. **Field Update Failed**: Verify field IDs and data types match between source and target
3. **Attachment Upload Failed**: Check file permissions and disk space
4. **Prefix Not Applied**: Ensure field supports prefix (string or ADF format)
