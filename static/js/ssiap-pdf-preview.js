/* PDF.js is served locally. The whole page is fitted to both viewport dimensions. */
(() => {
  'use strict';
  class SsiapPdfPreview {
    constructor(dialog, loader = () => import(dialog.dataset.pdfjsUrl)) {
      this.dialog = dialog;
      this.loader = loader;
      this.area = dialog.querySelector('[data-pdf-area]');
      this.canvas = dialog.querySelector('canvas');
      this.status = dialog.querySelector('[data-pdf-status]');
      this.pageLabel = dialog.querySelector('[data-pdf-page]');
      this.previous = dialog.querySelector('[data-pdf-previous]');
      this.next = dialog.querySelector('[data-pdf-next]');
      this.version = 0;
      this.renderVersion = 0;
      this.pageNumber = 1;
      this.zoom = 1;
      this.previous.addEventListener('click', () => this.go(-1));
      this.next.addEventListener('click', () => this.go(1));
      dialog.querySelector('[data-pdf-fit]').addEventListener('click', () => {this.zoom = 1; this.schedule();});
      dialog.querySelector('[data-pdf-zoom-in]').addEventListener('click', () => {this.zoom = Math.min(3, this.zoom * 1.25); this.schedule();});
      dialog.querySelector('[data-pdf-zoom-out]').addEventListener('click', () => {this.zoom = Math.max(1, this.zoom / 1.25); this.schedule();});
      dialog.querySelectorAll('[data-diploma-preview-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
      dialog.addEventListener('close', () => this.dispose());
      this.observer = new ResizeObserver(() => this.schedule());
      this.observer.observe(this.area);
    }
    dispose() {
      this.version++;
      this.renderVersion++;
      clearTimeout(this.timer);
      this.renderTask?.cancel();
      this.loading?.destroy()?.catch(() => {});
      this.loading = null;
      this.pdf = null;
      if (this.url) URL.revokeObjectURL(this.url);
      this.url = null;
      this.canvas.hidden = true;
    }
    async open(blob, {title = 'Prévisualisation des diplômes', description = 'Aperçu de vérification · Aucun numéro n’est attribué.', filename = 'apercu-diplomes-SSIAP.pdf'} = {}) {
      this.dispose();
      const version = this.version;
      this.pageNumber = 1; this.zoom = 1;
      this.status.textContent = 'Chargement du document…'; this.status.hidden = false;
      this.pageLabel.textContent = '';
      this.previous.disabled = this.next.disabled = true;
      this.url = URL.createObjectURL(blob);
      this.dialog.querySelector('h2').textContent = title;
      this.dialog.querySelector('[data-pdf-description]').textContent = description;
      this.dialog.querySelector('[data-diploma-open-preview]').href = this.url;
      const download = this.dialog.querySelector('[data-pdf-download]');
      download.href = this.url; download.download = filename;
      if (!this.dialog.open) this.dialog.showModal();
      try {
        const lib = await this.loader();
        if (version !== this.version) return;
        lib.GlobalWorkerOptions.workerSrc = this.dialog.dataset.pdfWorkerUrl;
        const buffer = await blob.arrayBuffer();
        if (version !== this.version) return;
        this.loading = lib.getDocument({data:buffer, standardFontDataUrl:this.dialog.dataset.pdfFontsUrl,
                                       useWasm:false, isEvalSupported:false});
        const pdf = await this.loading.promise;
        if (version !== this.version) return;
        this.pdf = pdf;
        await this.render();
      } catch (error) {
        if (version !== this.version) return;
        this.status.textContent = 'L’aperçu n’a pas pu être affiché. Vous pouvez ouvrir ou télécharger le PDF.';
        this.status.hidden = false;
      }
    }
    schedule() {
      clearTimeout(this.timer);
      if (this.pdf && this.dialog.open) this.timer = setTimeout(() => this.render(), 60);
    }
    async go(delta) {
      if (!this.pdf) return;
      this.pageNumber = Math.max(1, Math.min(this.pdf.numPages, this.pageNumber + delta));
      this.zoom = 1;
      await this.render();
    }
    async render() {
      if (!this.pdf || !this.dialog.open) return;
      const version = this.version, pageNumber = this.pageNumber, renderVersion = ++this.renderVersion;
      const oldTask = this.renderTask;
      if (oldTask) { oldTask.cancel(); try {await oldTask.promise;} catch {} }
      try {
        const page = await this.pdf.getPage(pageNumber);
        if (version !== this.version || renderVersion !== this.renderVersion) return;
        const natural = page.getViewport({scale:1});
        const width = Math.max(1, this.area.clientWidth - 32);
        const height = Math.max(1, this.area.clientHeight - 32);
        const scale = Math.min(width / natural.width, height / natural.height) * this.zoom;
        const viewport = page.getViewport({scale});
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        this.canvas.width = Math.ceil(viewport.width * ratio);
        this.canvas.height = Math.ceil(viewport.height * ratio);
        this.canvas.style.width = Math.floor(viewport.width) + 'px';
        this.canvas.style.height = Math.floor(viewport.height) + 'px';
        this.canvas.hidden = false;
        this.canvas.setAttribute('aria-label', `Page ${pageNumber} sur ${this.pdf.numPages}`);
        this.area.classList.toggle('is-zoomed', this.zoom > 1);
        this.previous.disabled = pageNumber <= 1;
        this.next.disabled = pageNumber >= this.pdf.numPages;
        this.pageLabel.textContent = `Page ${pageNumber} / ${this.pdf.numPages}`;
        this.renderTask = page.render({canvasContext:this.canvas.getContext('2d'), viewport,
                                       transform:ratio === 1 ? null : [ratio,0,0,ratio,0,0]});
        await this.renderTask.promise;
        if (version === this.version && renderVersion === this.renderVersion) this.status.hidden = true;
      } catch (error) {
        if (version === this.version && renderVersion === this.renderVersion && error.name !== 'RenderingCancelledException') {
          this.status.textContent = 'Impossible d’afficher cette page. Le PDF reste disponible en téléchargement.';
          this.status.hidden = false;
        }
      }
    }
  }
  window.SsiapPdfPreview = SsiapPdfPreview;
})();
