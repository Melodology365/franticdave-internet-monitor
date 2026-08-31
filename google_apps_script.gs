const CONFIG_FILE_ID = '1JqU-YY31WELMNoFaYZ2o8QpD6_4MDhJ7';
const OUTAGE_LOG_FILE_ID = '1u-znzx9WjLrkQIWviRtlPCbQBWaKA_2a';
const STATUS_LOG_FILE_ID = '1RQsGq7Yqh1y-uIxZmXB_DOnyVLNv-g1G';

function doGet(e) {
  try {
    const file = DriveApp.getFileById(CONFIG_FILE_ID);
    const contents = file.getBlob().getDataAsString();

    return ContentService
      .createTextOutput(contents)
      .setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return jsonResponse({ success: false, error: error.toString() });
  }
}

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);

    if (data.log_type === 'status') {
      appendStatusRow(data);
      return jsonResponse({ success: true, message: 'Status logged' });
    }

    appendOutageRow(data);
    return jsonResponse({ success: true, message: 'Outage logged' });
  } catch (error) {
    return jsonResponse({ success: false, error: error.toString() });
  }
}

function appendOutageRow(data) {
  const file = DriveApp.getFileById(OUTAGE_LOG_FILE_ID);
  const row = [
    csvValue(data.site_name || ''),
    csvValue(data.outage_started || ''),
    csvValue(data.outage_ended || ''),
    csvValue(data.duration_seconds || ''),
    csvValue(data.duration_minutes || ''),
    csvValue(data.email_required || ''),
    csvValue(data.email_sent || '')
  ].join(',');

  appendCsvRow(file, row);
}

function appendStatusRow(data) {
  const file = DriveApp.getFileById(STATUS_LOG_FILE_ID);
  const row = [
    csvValue(data.site_name || ''),
    csvValue(data.entry_type || ''),
    csvValue(data.timestamp || ''),
    csvValue(data.monitor_started || ''),
    csvValue(data.monitor_uptime_hours || ''),
    csvValue(data.total_checks || 0),
    csvValue(data.failed_checks || 0),
    csvValue(data.total_outages || 0),
    csvValue(data.session_outages || 0),
    csvValue(data.last_outage_started || ''),
    csvValue(data.last_outage_duration_seconds || ''),
    csvValue(data.current_status || '')
  ].join(',');

  appendCsvRow(file, row);
}

function appendCsvRow(file, row) {
  let existing = file.getBlob().getDataAsString();

  if (existing.length > 0 && !existing.endsWith('\n')) {
    existing += '\n';
  }

  existing += row + '\n';
  file.setContent(existing);
}

function csvValue(value) {
  const text = String(value);

  if (text.includes(',') || text.includes('"') || text.includes('\n')) {
    return '"' + text.replace(/"/g, '""') + '"';
  }

  return text;
}

function jsonResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
