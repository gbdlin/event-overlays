import {createApp, ref, computed} from 'vue'

let ws;
const m_state = ref(null);
const m_customTimeDialog = ref(false);
const m_timerFlashing = ref(false);
const m_now = ref(Date.now());
setInterval(() => m_now.value = Date.now(), 69);
const body = document.getElementsByTagName("body")[0];

function sendMessage(data) {
  ws.send(JSON.stringify(data));
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
      let data = JSON.parse(event.data);
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
        sendMessage({"action": "ntc.sync", "client_time": Date.now()});
      }
      if (m_state.value === null) {
        m_state.value = {}
      }
      delete data.status;
      Object.assign(m_state.value, data);
      console.log(data);
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

openSocket(`${location.origin.replace("http", "ws")}${body.dataset.ws}`, 1000, 1000, 2)

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
      meeting_name: body.dataset.title,
      state: m_state,
      timerFlashing: m_timerFlashing,
      displayMessages: computed(() => (
        m_state.value.template === "agenda"
        || m_state.value.template === "brb"
      )),
      messagesPositionCls: computed(() => ({
        "alt-position": m_state.value.template === "agenda",
      })),
      getStateDisplay: function (state) {
        return `${state[1] ? "Mid" : "Pre"} #${state[0] + 1}`
      },
      handleAction(action_name) {
        if (action_name === "stream.set-message")
          sendMessage({"action": action_name, "message": m_state.value.message});
        else if (action_name === "timer.set-message")
          sendMessage({"action": action_name, "message": m_state.value.timer.message});
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
      showCustomTimeDialog(e) {
        document.getElementById("timer-custom-dialog").showModal();
      },
    }
  }
}).mount('#app');
