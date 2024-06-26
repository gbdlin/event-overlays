import {createApp, ref, computed} from 'vue'

let ws;
let branding_style = null;
const m_state = ref(null);
const m_meeting = ref(null);
const m_role = ref(null);
const m_timerFlashing = ref(false);
const m_now = ref(Date.now());
const m_assignTarget = ref(null);
const m_viewName = ref(null);
setInterval(() => m_now.value = Date.now(), 69);
const m_ticker = ref(0);
setInterval(() => m_ticker.value += 100, 100);
const initSettings = JSON.parse(document.getElementById("initSettings").textContent)
const dateFormatter = new Intl.DateTimeFormat('default', {hour12: false, timeZone: "Europe/Warsaw", timeStyle: "short"})

function sendMessage(data) {
  ws.send(JSON.stringify(data));
}

function set_branding(name, version) {
  if (branding_style && !name) {
    branding_style.remove();
    return
  }
  if (!name) {
    return
  }
  if (!branding_style) {
    branding_style = document.createElement('link');
    branding_style.rel = 'stylesheet';
    document.head.appendChild(branding_style);
  }
  branding_style.href = `/static/branding/${name}.css?v=${version}`;
}

const parseEventData = (data) => {
  if (data.status === "unassigned") {
    m_viewName.value = data.name;
    m_state.value = null;
    return;
  }
  if (data.status === "success")
    return;
  if (data.status === "timer.flash") {
    m_timerFlashing.value = true;
    setTimeout(() => m_timerFlashing.value = false, 3000);
  }
  if (data.status === "error") {
    console.log("ws error")
    console.log(data);
    return;
  }
  if (data.status === "ntc.sync") {
    let client_time = Date.now();
    let client_offset = data.server_time - client_time;
    let avg_offset = (client_offset + data.offset) / 2;
    console.log(data);
    console.log(client_offset);
    console.log(avg_offset);
    return
  }
  if (data.status === "init") {
    if (ws !== undefined)
      sendMessage({"action": "ntc.sync", "client_time": Date.now()});
    m_meeting.value = {};
    Object.assign(m_meeting.value, data.meeting)
    m_role.value = data.role;
    set_branding(data.meeting.branding, data.meeting.branding_sha);
  }
  if (m_state.value === null) {
    m_state.value = {};
  }
  delete data.status;
  Object.assign(m_state.value, data);
  console.log(data);
}

const openSocket = (wsURL, waitTimer, waitSeed, multiplier) => {
  ws = new WebSocket(wsURL);
  console.log(`trying to connect to: ${ws.url}`);

  ws.onopen = () => {
    console.log(`connection open to: ${ws.url}`);
    waitTimer = waitSeed; //reset the waitTimer if the connection is made

    ws.onclose = () => {
      console.log(`connection closed to: ${ws.url}`);
      openSocket(ws.url, waitTimer, waitSeed, multiplier);
    };

    ws.onmessage = (event) => {
      parseEventData(JSON.parse(event.data));
    };
  };

  ws.onerror = () => {
    //increaese the wait timer if not connected, but stop at a max of 2n-1 the check time
    if (waitTimer < 60000)
      waitTimer = waitTimer * multiplier;
    console.log(`error opening connection ${ws.url}, next attemp in : ${waitTimer / 1000} seconds`);
    setTimeout(() => {
      openSocket(ws.url, waitTimer, waitSeed, multiplier)
    }, waitTimer);
  }
}

if (initSettings.ws !== undefined) {
  openSocket(`${location.origin.replace("http", "ws")}${initSettings.ws}`, 1000, 1000, 2)
} else {
  parseEventData(initSettings.data)
}

function timerPieces(value) {
  const round_fn = value > 0 ? Math.floor : Math.ceil;
  const sign = value >= 0 ? "" : "-"

  const s_msec = Math.abs(value % 1000);
  const seconds = round_fn(value / 1000);
  const minutes = Math.abs(round_fn(seconds / 60));
  const m_seconds = Math.abs(seconds % 60);

  const f_minutes = `${sign}${minutes}`
  const f_seconds = String(m_seconds).padStart(2, "0");
  const f_msec = String(s_msec).padStart(3, "0");

  return [f_minutes, f_seconds, f_msec]
}

createApp({
  data() {
    return {
      meeting: m_meeting,
      display: computed(() => (
        initSettings.display || m_meeting.value.template.default_display
      )),
      presentationBottomBar: initSettings.presentationBottomBar,
      presentationSponsors: initSettings.presentationSponsors,
      state: m_state,
      assignTarget: m_assignTarget,
      viewName: m_viewName,
      timerFlashing: m_timerFlashing,
      displayMessages: computed(() => (
        m_state.value.template === "schedule"
        || m_state.value.template === "message"
      )),
      messagesPositionCls: computed(() => ({
        "alt-position": m_state.value.template === "schedule",
      })),
      getStateDisplay: function (state) {
        return `${state[1] ? "Mid" : "Pre"} #${state[0] + 1}`
      },
      handleAction(action_name) {
        if (action_name === "stream.set-message")
          sendMessage({"action": action_name, "message": m_state.value.message});
        else if (action_name === "timer.set-message")
          sendMessage({"action": action_name, "message": m_state.value.timer.message});
        else if (action_name === "view.assign")
          sendMessage({"action": action_name, "view_name": m_assignTarget.value})
        else
          sendMessage({"action": action_name});
      },
      current: computed(() => m_state.value.context.entry),
      timerSeconds(value) {
        return timerPieces(value)[1];
      },
      timerMinutes(value) {
        return timerPieces(value)[0];
      },
      timerValue: computed(function () {
        let tick;
        if (m_state.value.timer.started_at === null)
          tick = 0;
        else
          tick = m_now.value - m_state.value.timer.started_at;

        return m_state.value.timer.target - m_state.value.timer.offset - tick;
      }),
      timerFormat(value) {
        const [minutes, f_seconds] = timerPieces(value);

        return `${minutes}:${f_seconds}`
      },
      timerFormatMsec(value) {
        const [minutes, f_seconds, f_msec] = timerPieces(value);
        return `${minutes}:${f_seconds}.${f_msec}`
      },
      setTimer(value) {
        sendMessage({"action": "timer.set", "time": value});
      },
      adjustTimer(value) {
        sendMessage({"action": "timer.set", "time": Math.max(m_state.value.timer.target + value, 0)});
      },
      showDialog(name) {
        document.getElementById(`${name}-dialog`).showModal();
      },
      ticker: m_ticker,
      slideActive(ticker, time, index, total) {
        const current = ticker % (time * total)
        return (current >= time * index && current < time * (index + 1));
      },
      formatTime(datetime) {
        const date = new Date(datetime);
        return dateFormatter.format(date);
      }
    }
  }
}).mount('#app');
