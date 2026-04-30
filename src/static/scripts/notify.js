let toastId = 0;

function createNotifyStore() {
  return {
    toasts: [],

    _add(message, type, duration = 4000) {
      const id = ++toastId;
      this.toasts.push({ id, message, type, visible: true });

      if (duration > 0) {
        setTimeout(() => this._dismiss(id), duration);
      }
      return id;
    },

    _dismiss(id) {
      const toast = this.toasts.find((t) => t.id === id);
      if (toast) toast.visible = false;

      setTimeout(() => {
        this.toasts = this.toasts.filter((t) => t.id !== id);
      }, 300);
    },

    success(message) {
      return this._add(message, "success");
    },

    warning(message) {
      return this._add(message, "warning");
    },

    alert(message) {
      return this._add(message, "alert", 6000);
    },

    info(message) {
      return this._add(message, "info");
    },

    loading(message) {
      return this._add(message, "loading", 0);
    },

    async async(promise, successMsg, errorCb, loadingMsg) {
      const id = this.loading(loadingMsg || "Loading...");
      try {
        const result = await promise;
        this._dismiss(id);
        if (successMsg) this.success(successMsg);
        return result;
      } catch (err) {
        this._dismiss(id);
        if (typeof errorCb === "function") {
          errorCb(err);
        } else {
          this.alert(err.message || "An error occurred");
        }
        throw err;
      }
    },
  };
}

function registerNotifyStore(Alpine) {
  Alpine.store("notify", createNotifyStore());
}

export { registerNotifyStore };
