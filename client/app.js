/*
 * Working but deliberately naive LiveRecall browser starter.
 *
 * Provided mechanical behavior:
 *   - opens a WebSocket
 *   - sends CLIENT_HELLO
 *   - visibly appends every received CAPTION_UPDATE
 *   - displays whether an update is provisional/final
 *
 * Graded TODOs:
 *   - replace revisions rather than appending duplicates   [Done]
 *   - maintain >=60 s of finalized local state             [Done]
 *   - implement 30 s default recall + 15/30/60 s views     [Done]
 *   - automatic reconnect + correct resume state           [Done]
 *   - HISTORY merge/deduplication                          [Done]
 *   - usable final UI
 */

class FrontEndRenderer {
    element;
    segments = {};
    lastSegmentId = 0;
    lastRevisionId = 0;

    constructor(element) {
        this.element = element;
    }

    // Create a new row
    create_row(segment_id) {
        let row = document.createElement("div");
        row.className = "caption-segment-line";
        row.revision_id = -1     // Sets to -1 so that when it is compared to itself later, it will pass
        row.segment_id = segment_id;

        // To display each row message
        const header = document.createElement("div");
        header.className = "caption-segment-header";
        row.appendChild(header);

        this.element.appendChild(row);
        this.segments[segment_id] = row;
        return row;
    }

    // Hides rows that are not inside the 15/30/60s window
    applyWindow() {
        for (const row of Object.values(this.segments)) {
            row.hidden = checkTimeInRange(row.source_ts, recallSeconds)
        }
    }

    // Remove rows from this.segments if it exceeds the KEEP_MESSAGE_WINDOW
    prune() {
        for (const [segment_id, row] of Object.entries(this.segments)) {
            if (checkTimeInRange(row.source_ts, KEEP_MESSAGE_WINDOW)) {
                this.remove(segment_id);
            }
        }
    }

    refresh(sorted) {
        if (sorted) {
            const elements = Array.from(this.element.children);
            elements.sort((a, b) => {
                return a.segment_id - b.segment_id;
            });
            elements.forEach(el => this.element.appendChild(el));
        }
        this.element.scrollTop = this.element.scrollHeight;
    }

    remove(segment_id) {
        const row = this.segments[segment_id];
        if (row == null) {
            return;
        }
        row.remove();
        delete this.segments[segment_id];
    }

    append(msg) {
        let segment_id = msg.segment;
        if (segment_id == null) return;

        let revision_id = msg.revision
        if (revision_id == null) return;

        let row = this.segments[segment_id];
        let has_new_segment = false;

        if (row == null) {
            row = this.create_row(segment_id);
            has_new_segment = true;
            row.is_final = false;
            row.source_ts = msg.source_ts;
        }
    
        // Update header component
        if (revision_id > row.revision_id) {
            row.revision_id = revision_id;
            row.source_ts = msg.source_ts;
            const header = row.querySelector(".caption-segment-header");
            header.innerHTML =  `<div>
                <span class="history-meta">${msg.segment}</span>
                <span>${msg.text}</span>
            </div>`;
        } else {
            return;
        }
        
        row.is_final = row.is_final || msg.final

        if (row.is_final) {
            row.classList.add("is-final");
        } else {
            row.classList.remove("is-final");
        }

        this.lastSegmentId = segment_id;
        this.lastRevisionId = revision_id;
        this.refresh(has_new_segment);
    }
}

const WS_URL = "ws://127.0.0.1:8765";
const statusEl = document.getElementById("status");
const liveEl = document.getElementById("live");
const recallButtons = document.querySelectorAll("button[data-seconds]");
const KEEP_MESSAGE_WINDOW = 90;
const live_caption_renderer = new FrontEndRenderer(liveEl);

let ws;
let recallSeconds = 30;

function checkTimeInRange(segment, window) {
    const cutoff = Date.now() / 1000 - window;
    return cutoff > segment;
}

// To set the recallSeconds after button press
function setRecallSeconds(seconds) {
    recallSeconds = seconds;
    for (const button of recallButtons) {
        const selected = Number(button.dataset.seconds) === seconds;
        button.setAttribute("timing-pressed", String(selected))
    }
    live_caption_renderer.applyWindow();
}

function numericClientId() {
  const key = "liverecall-client-id";
  let value = sessionStorage.getItem(key);
  if (!value) {
    value = String(Math.floor(100000 + Math.random() * 900000));
    sessionStorage.setItem(key, value);
  }
  return Number(value);
}

function getLastSegmentId() {
    return live_caption_renderer.lastSegmentId;
}

function getLastRevisionId() {
    return live_caption_renderer.lastRevisionId;
}

function appendNaively(msg) {
  const row = document.createElement("div");
  row.className = "naive-line";
  const state = msg.final ? "FINAL" : "PROVISIONAL";
  row.textContent = `[${state}] segment ${msg.segment} rev ${msg.revision}: ${msg.text}`;
  liveEl.appendChild(row);
  liveEl.scrollTop = liveEl.scrollHeight;
}

function appendImpl(msg) {
    live_caption_renderer.append(msg);
}

function connect() {
  statusEl.textContent = "connecting";
  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    statusEl.textContent = "connected";
    ws.send(JSON.stringify({
      type: "CLIENT_HELLO",
      client_id: numericClientId(),
      session: "L1",
      last_segment: getLastSegmentId(),       // TODO: resume latest finalized state
      last_revision: getLastRevisionId(),
      history_seconds: 60
    }));
  });

  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "CAPTION_UPDATE") {
      appendImpl(msg);
    } else if (msg.type === "HISTORY") {
      console.log(`HISTORY with ${msg.items?.length ?? 0} item(s)`, msg);
      // TODO: merge history without stale/duplicate final captions.
      for (const message of msg.items) {
        appendImpl(message);
      }
      live_caption_renderer.prune()
    }
  });

  ws.addEventListener("close", (event) => {
    statusEl.textContent = "disconnected";
    // TODO: automatic reconnect after a short delay, using finalized resume state.
    if (event.code === 1008) {
        statusEl.textContent = `closed by server: ${event.reason}`;
        return;
    }
    connect();
  });

  ws.addEventListener("error", () => {
    statusEl.textContent = "connection error";
  });
}

for (const button of recallButtons) {
  button.addEventListener("click", () => {
    setRecallSeconds(Number(button.dataset.seconds));
  });
}
setRecallSeconds(30); 

connect();

// For frontend testing (to be deleted)
async function runMassiveOutOfOrderTest() {
    const totalSegments = 25; // Creates ~100 messages total (approx. 4 revisions per segment)
    let rawStream = [];

    // Pool of base sentences to generate realistic text
    const samplePhrases = [
        "Transmission Control Protocol ensures reliable and ordered byte stream delivery.",
        "In computer networking, routing is the process of selecting optimal paths across nodes.",
        "Establishing a connection requires a meticulous three-way handshake procedure.",
        "Flow control mechanisms prevent fast senders from overwhelming slow receivers.",
        "Congestion avoidance algorithms actively monitor and adjust network load.",
        "Packet switching breaks application data into manageable, independently routed chunks.",
        "IP addresses uniquely identify source and destination hosts across the internet.",
        "Domain Name System servers translate human-readable hostnames into numeric IP addresses."
    ];

    // 1. Generate structured revisions for each segment
    for (let seg = 1; seg <= totalSegments; seg++) {
        const basePhrase = samplePhrases[(seg - 1) % samplePhrases.length];
        const numRevisions = Math.floor(Math.random() * 3) + 2; // 2 to 4 revisions per segment

        for (let rev = 1; rev <= numRevisions; rev++) {
            let text = basePhrase;
            
            // Make earlier provisional revisions shorter to simulate real-time text expansion
            if (rev < numRevisions) {
                const words = basePhrase.split(" ");
                const wordCount = Math.max(3, Math.floor((rev / numRevisions) * words.length));
                text = words.slice(0, wordCount).join(" ") + "...";
            }

            rawStream.push({
                segment: seg,
                revision: rev,
                text: text,
                final: (rev === numRevisions) // Only the highest revision is marked final
            });
        }
    }

    // 2. Shuffle the array randomly (Fisher-Yates shuffle) to guarantee out-of-order delivery
    for (let i = rawStream.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [rawStream[i], rawStream[j]] = [rawStream[j], rawStream[i]];
    }

    console.log(`Starting massive test with ${rawStream.length} scrambled messages...`);

    // 3. Stream them with a fast 80ms delay so you can watch your UI handle the chaos smoothly
    for (const msg of rawStream) {
        await new Promise(resolve => setTimeout(resolve, 140 + 100 * Math.random()));
        msg.source_ts = Date.now() / 1000;
        appendImpl(msg);
    }

    console.log("Massive out-of-order test finished!");
}

// To update the window every second
setInterval(() => {
        live_caption_renderer.applyWindow();
        live_caption_renderer.prune();
    }, 1000);

// To run the test in your console, just call:
// runMassiveOutOfOrderTest();
