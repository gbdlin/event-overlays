import {createApp, ref, computed} from 'vue'

const m_state = ref(
  {
    tick: 0,
    sponsorsPosition: "",
    display: "",
    bottomBar: true,
  }
);
const initSettings = JSON.parse(document.getElementById("initSettings").textContent);
const event = initSettings.event;
const max_tick = (event.schedule.length) * 2 - 1;

function stateSlug() {
  return `${Math.floor(m_state.value.tick / 2)}-${m_state.value.tick % 2? 'mid' : 'pre'}`
}

createApp({
  data() {
    return {
      event: event,
      state: m_state,
      stateSlug: computed(stateSlug),
      stateDisplay: computed(function () {
        return `${m_state.value.tick % 2? 'Mid' : 'Pre'} #${Math.floor(m_state.value.tick / 2 + 1)}`
      }),
      tick: function () {
        m_state.value.tick = Math.min(max_tick, m_state.value.tick + 1)
        console.log(m_state.value)
      },
      untick: function () {
        m_state.value.tick = Math.max(0, m_state.value.tick - 1)
        console.log(m_state.value)
      },
      maxTick: computed(function () {
        return m_state.value.tick >= max_tick;
      }),
      maxUntick: computed(function () {
        return m_state.value.tick <= 0;
      }),

      scheduleUrl: computed(function () {
        const url = new URL(`/v1/events/${event.path}/views/schedule/${stateSlug()}`, window.location.origin)
        const searchParams = [];
        if (m_state.value.display) {
          searchParams.push(`display=${m_state.value.display}`)
        }
        url.search = searchParams.join("&")
        return url
      }),
      titleUrl: computed(function () {
        return new URL(`/v1/events/${event.path}/views/title/${stateSlug()}`, window.location.origin)
      }),
      presentationUrl: computed(function () {
        const url = new URL(`/v1/events/${event.path}/views/presentation/${stateSlug()}`, window.location.origin)
        const searchParams = [];
        if (m_state.value.sponsorsPosition) {
          searchParams.push(`presentation_sponsors=${m_state.value.sponsorsPosition}`)
        }
        if (!m_state.value.bottomBar) {
          searchParams.push("presentation_bottom_bar=false")
        }
        url.search = searchParams.join("&")
        return url
      }),
      brbUrl: computed(function () {
        return new URL(`/v1/events/${event.path}/views/brb/${stateSlug()}`, window.location.origin)
      }),
    }
  }
}).mount('#app');
