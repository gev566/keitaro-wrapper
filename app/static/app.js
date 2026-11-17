/* Интерфейс на Vue 3 без сборки: один файл, запросы к нашему API через fetch. */

const { createApp } = Vue;

async function api(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* пустой ответ */
  }
  if (!response.ok) {
    const detail = data && data.detail;
    const text = Array.isArray(detail) ? detail.map((item) => item.msg).join('; ') : detail;
    throw new Error(text || `Ошибка ${response.status}`);
  }
  return data;
}

/* Поле выбора оффера с поиском (автокомплит). v-model — объект { id, name } или null. */
const OfferPicker = {
  props: { modelValue: Object, placeholder: String },
  emits: ['update:modelValue'],
  data() {
    return { query: '', items: [], open: false, timer: null };
  },
  watch: {
    modelValue(value) {
      if (!value) this.query = '';
    },
  },
  methods: {
    onInput() {
      this.$emit('update:modelValue', null);
      clearTimeout(this.timer);
      // ждём паузу в наборе, чтобы не слать запрос на каждую букву
      this.timer = setTimeout(this.search, 250);
    },
    async search() {
      try {
        this.items = await api('GET', '/api/offers?q=' + encodeURIComponent(this.query));
        this.open = true;
      } catch {
        this.items = [];
      }
    },
    pick(item) {
      this.query = `${item.id} ${item.name}`;
      this.open = false;
      this.$emit('update:modelValue', item);
    },
    close() {
      // небольшая задержка, чтобы успел сработать клик по пункту списка
      setTimeout(() => { this.open = false; }, 150);
    },
  },
  template: `
    <div class="picker">
      <input v-model="query" :placeholder="placeholder" autocomplete="off"
             @input="onInput" @focus="search" @blur="close">
      <ul v-if="open" class="picker-list">
        <li v-for="item in items" :key="item.id">
          <button type="button" @mousedown.prevent="pick(item)">
            <span class="muted">{{ item.id }}</span> {{ item.name }}
          </button>
        </li>
        <li v-if="!items.length" class="muted pad">Нет такого оффера.</li>
      </ul>
    </div>`,
};

createApp({
  components: { OfferPicker },
  data() {
    return {
      meta: { domains: [], groups: [], sources: [], defaults: {}, prefix: '', redirect_url: '' },
      form: { name: '', geo: '', offer: null, domain_id: null, group_id: null, source_id: null },
      campaign: null,
      keitaroCampaigns: [],
      campaignQuery: '',
      picked: {},
      busy: false,
      queue: Promise.resolve(),
      error: '',
      notice: '',
    };
  },
  async mounted() {
    await this.run(async () => {
      this.meta = await api('GET', '/api/meta');
      Object.assign(this.form, this.meta.defaults);
    });
    this.searchCampaigns();
  },
  methods: {
    /* Общая обёртка: выполняет запросы строго по очереди и показывает ошибку.
       Очередь нужна, чтобы два быстрых клика не отправили запросы одновременно. */
    run(action, notice) {
      this.queue = this.queue.then(async () => {
        this.busy = true;
        this.error = '';
        this.notice = '';
        try {
          await action();
          if (notice) this.notice = notice;
        } catch (error) {
          this.error = error.message;
        } finally {
          this.busy = false;
        }
      });
      return this.queue;
    },
    replaceStream(updated) {
      const index = this.campaign.streams.findIndex((stream) => stream.id === updated.id);
      if (index !== -1) this.campaign.streams[index] = updated;
    },

    createCampaign() {
      return this.run(async () => {
        this.campaign = await api('POST', '/api/campaigns', {
          name: this.form.name,
          geo: this.form.geo,
          offer_id: this.form.offer.id,
          domain_id: this.form.domain_id,
          group_id: this.form.group_id,
          source_id: this.form.source_id,
        });
        this.form.name = '';
        this.form.geo = '';
        this.form.offer = null;
        this.searchCampaigns();
      }, 'Кампания создана в Keitaro.');
    },
    async searchCampaigns() {
      try {
        this.keitaroCampaigns = await api('GET', '/api/keitaro/campaigns?q=' + encodeURIComponent(this.campaignQuery));
      } catch (error) {
        this.error = error.message;
      }
    },
    openCampaign(keitaroId) {
      return this.run(async () => {
        this.campaign = await api('POST', '/api/campaigns/open', { keitaro_id: keitaroId });
      });
    },
    fetchStreams() {
      return this.run(async () => {
        this.campaign = await api('POST', `/api/campaigns/${this.campaign.id}/fetch`);
      }, 'Потоки обновлены из Keitaro.');
    },

    addOffer(stream) {
      return this.run(async () => {
        this.replaceStream(await api('POST', `/api/streams/${stream.id}/offers`, { offer_id: this.picked[stream.id].id }));
        this.picked[stream.id] = null;
      });
    },
    removeOffer(offer) {
      return this.run(async () => this.replaceStream(await api('DELETE', `/api/stream-offers/${offer.id}`)));
    },
    restoreOffer(offer) {
      return this.run(async () => this.replaceStream(await api('POST', `/api/stream-offers/${offer.id}/restore`)));
    },
    setPin(offer, pinned, share) {
      return this.run(async () => {
        this.replaceStream(await api('PATCH', `/api/stream-offers/${offer.id}`, { pinned, share: Number(share) }));
      });
    },
    pushStream(stream) {
      return this.run(async () => this.replaceStream(await api('POST', `/api/streams/${stream.id}/push`)), 'Изменения отправлены в Keitaro.');
    },
    cancelStream(stream) {
      return this.run(async () => this.replaceStream(await api('POST', `/api/streams/${stream.id}/cancel`)));
    },
  },
}).mount('#app');
