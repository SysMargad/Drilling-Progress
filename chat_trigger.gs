// Google Apps Script: starts .github/workflows/chat-report.yml every evening so
// drilling progress reaches Google Chat at 20:00 UTC+8. GitHub's own schedule
// started runs 5–7 hours late; Apps Script time triggers fire within ±15 minutes.
//
// Script property GITHUB_TOKEN: fine-grained token for SysMargad/Drilling-Progress
// with Actions read and write permission.

const REPO = 'SysMargad/Drilling-Progress';
const WORKFLOW = 'chat-report.yml';

function postDrillingProgress() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Set the GITHUB_TOKEN script property.');
  const response = UrlFetchApp.fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
      method: 'post',
      contentType: 'application/json',
      headers: {Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json'},
      // The workflow waits for 20:00 before posting.
      payload: JSON.stringify({ref: 'main', inputs: {evening: 'true'}}),
      muteHttpExceptions: true,
    });
  const code = response.getResponseCode();
  // A thrown error makes Apps Script email the owner about the failed run.
  if (code < 200 || code >= 300) throw new Error(`GitHub ${code}: ${response.getContentText()}`);
}

// Run once from the editor to create (or recreate) the daily trigger.
function install() {
  ScriptApp.getProjectTriggers()
    .filter((trigger) => trigger.getHandlerFunction() === 'postDrillingProgress')
    .forEach((trigger) => ScriptApp.deleteTrigger(trigger));
  // nearMinute allows ±15 minutes, so the run starts between 19:30 and 20:00.
  ScriptApp.newTrigger('postDrillingProgress').timeBased()
    .atHour(19).nearMinute(45).everyDays(1).inTimezone('Asia/Ulaanbaatar').create();
}
