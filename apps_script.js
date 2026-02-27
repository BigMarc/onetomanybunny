/**
 * ══════════════════════════════════════════════════════════════
 * Bunny Clip Tool — Google Apps Script (Drive Monitor)
 * ══════════════════════════════════════════════════════════════
 *
 * This script monitors Google Drive folders for new creator videos
 * and automatically triggers Cloud Run processing.
 *
 * HOW TO SET UP:
 * 1. Go to https://script.google.com
 * 2. Create a new project
 * 3. Paste this entire file
 * 4. Fill in the 3 constants below
 * 5. Run installTrigger() once
 * 6. Approve OAuth permissions when prompted
 *
 * The script runs every 5 minutes and checks each creator's
 * "UPLOAD HERE" folder for new videos.
 */

// ── CONFIGURATION — FILL THESE IN ──────────────────────────────────────────

/**
 * Your Cloud Run processor URL (from deploy.sh output).
 * Example: "https://bunny-clip-processor-abc123-uc.a.run.app"
 */
var CLOUD_RUN_URL = "PASTE_YOUR_CLOUD_RUN_PROCESSOR_URL_HERE";

/**
 * Map of creator names to their "UPLOAD HERE" Drive folder IDs.
 * Find folder IDs in the URL when you open each folder in Google Drive.
 * Example: https://drive.google.com/drive/folders/1ABC... → "1ABC..."
 */
var CREATOR_FOLDERS = {
  // "Sofia": "1abc_FOLDER_ID_for_Sofia_UPLOAD_HERE",
  // "Lena":  "1def_FOLDER_ID_for_Lena_UPLOAD_HERE",
  // "Maria": "1ghi_FOLDER_ID_for_Maria_UPLOAD_HERE",
};

/**
 * Email address to receive success/failure notifications.
 */
var NOTIFY_EMAIL = "marc@bunny-agency.com";


// ── MAIN SCANNER ────────────────────────────────────────────────────────────

/**
 * Main entry point — scans all creator folders for new videos.
 * Called automatically by the time-based trigger every 5 minutes.
 */
function scanAllCreatorFolders() {
  var creatorNames = Object.keys(CREATOR_FOLDERS);

  if (creatorNames.length === 0) {
    Logger.log("No creator folders configured. Add entries to CREATOR_FOLDERS.");
    return;
  }

  Logger.log("Scanning " + creatorNames.length + " creator folders...");

  for (var i = 0; i < creatorNames.length; i++) {
    var creatorName = creatorNames[i];
    var folderId = CREATOR_FOLDERS[creatorName];

    try {
      scanCreatorFolder(creatorName, folderId);
    } catch (e) {
      Logger.log("ERROR scanning " + creatorName + ": " + e.message);
      sendNotification(
        "❌ Scan Error — " + creatorName,
        "Failed to scan folder for " + creatorName + ".\n\n" +
        "Error: " + e.message + "\n\n" +
        "Folder ID: " + folderId
      );
    }
  }
}


/**
 * Scan a single creator's folder for unprocessed videos.
 *
 * Logic:
 * - Lists all video files in the folder
 * - Skips files already prefixed with [PROCESSING], [DONE], or [FAILED]
 * - Marks new videos as [PROCESSING] before triggering
 * - Marks as [DONE] or [FAILED] after Cloud Run responds
 */
function scanCreatorFolder(creatorName, folderId) {
  var folder = DriveApp.getFolderById(folderId);
  var files = folder.getFiles();
  var videoMimeTypes = [
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm"
  ];

  while (files.hasNext()) {
    var file = files.next();
    var fileName = file.getName();
    var mimeType = file.getMimeType();

    // Skip non-video files
    if (videoMimeTypes.indexOf(mimeType) === -1) {
      continue;
    }

    // Skip already-processed files
    if (fileName.indexOf("[PROCESSING]") === 0 ||
        fileName.indexOf("[DONE]") === 0 ||
        fileName.indexOf("[FAILED]") === 0) {
      continue;
    }

    Logger.log("Found new video for " + creatorName + ": " + fileName);

    // Mark as processing
    file.setName("[PROCESSING] " + fileName);

    // Trigger Cloud Run
    var success = triggerCloudRun(file.getId(), creatorName);

    if (success) {
      file.setName("[DONE] " + fileName);
      Logger.log("✅ Done: " + fileName);
      sendNotification(
        "✅ Video Processed — " + creatorName,
        "Video: " + fileName + "\n" +
        "Creator: " + creatorName + "\n\n" +
        "Clips should now be in the _PROCESSED Drive folder."
      );
    } else {
      file.setName("[FAILED] " + fileName);
      Logger.log("❌ Failed: " + fileName);
      sendNotification(
        "❌ Processing Failed — " + creatorName,
        "Video: " + fileName + "\n" +
        "Creator: " + creatorName + "\n\n" +
        "Cloud Run processing failed. Check Cloud Run logs for details.\n" +
        "File ID: " + file.getId()
      );
    }
  }
}


// ── CLOUD RUN TRIGGER ───────────────────────────────────────────────────────

/**
 * POST to Cloud Run /process endpoint with the video file ID and creator name.
 *
 * @param {string} fileId - Google Drive file ID of the video
 * @param {string} creatorName - Name of the creator
 * @returns {boolean} true if Cloud Run returned 200, false otherwise
 */
function triggerCloudRun(fileId, creatorName) {
  var url = CLOUD_RUN_URL + "/process";
  var payload = {
    "video_file_id": fileId,
    "creator_name": creatorName
  };

  var options = {
    "method": "post",
    "contentType": "application/json",
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true,
    "headers": {
      "Content-Type": "application/json"
    }
  };

  try {
    var response = UrlFetchApp.fetch(url, options);
    var code = response.getResponseCode();
    var body = response.getContentText();

    Logger.log("Cloud Run response (" + code + "): " + body.substring(0, 500));

    if (code === 200) {
      return true;
    } else {
      Logger.log("Cloud Run error: HTTP " + code + " — " + body);
      return false;
    }
  } catch (e) {
    Logger.log("Cloud Run request failed: " + e.message);
    return false;
  }
}


// ── TRIGGER INSTALLER ───────────────────────────────────────────────────────

/**
 * Install a time-based trigger that runs scanAllCreatorFolders every 5 minutes.
 *
 * Run this function ONCE manually from the Apps Script editor:
 * 1. Select "installTrigger" from the function dropdown
 * 2. Click "Run"
 * 3. Approve OAuth permissions when prompted
 *
 * To verify: go to Triggers (clock icon in left sidebar) and confirm the trigger exists.
 */
function installTrigger() {
  // Remove any existing triggers for this function to avoid duplicates
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "scanAllCreatorFolders") {
      ScriptApp.deleteTrigger(triggers[i]);
      Logger.log("Removed existing trigger");
    }
  }

  // Create new 5-minute trigger
  ScriptApp.newTrigger("scanAllCreatorFolders")
    .timeBased()
    .everyMinutes(5)
    .create();

  Logger.log("✅ Trigger installed: scanAllCreatorFolders runs every 5 minutes");
  Logger.log("   Go to Triggers (⏰) to verify");
}


// ── EMAIL NOTIFICATIONS ─────────────────────────────────────────────────────

/**
 * Send an email notification.
 *
 * @param {string} subject - Email subject line
 * @param {string} body - Email body text
 */
function sendNotification(subject, body) {
  if (!NOTIFY_EMAIL) {
    Logger.log("No NOTIFY_EMAIL configured — skipping notification");
    return;
  }

  try {
    MailApp.sendEmail({
      to: NOTIFY_EMAIL,
      subject: subject,
      body: body + "\n\n— Bunny Clip Tool (Apps Script)"
    });
  } catch (e) {
    Logger.log("Failed to send email: " + e.message);
  }
}
