"use strict";
const EdofTest = (() => {
  const ORIGIN = "https://gestionstagiaires-test-v2.onrender.com";
  const SIRET = "84089988400026";
  const fields = ["id", "trainingId", "trainingActionId", "currentState", "beginDate", "endDate", "currentBillingState", "billingDate", "paymentState", "codeReconnaissance"];
  const attendeeFields = ["firstName", "lastName", "email"];
  const infoFields = ["title", "sessionId", "sessionStartDate", "sessionEndDate", "totalIncl", "teachingFees", "indicativeDuration", "hoursInCenter", "trainingCompletionRate", "validatedServiceDone"];
  function parseKey(value) {
    if (typeof value !== "string") return null;
    const match = /^edoftest1\.([0-9]{6,20})\.([A-Za-z0-9_-]{43})$/.exec(value.trim());
    return match ? {id: match[1], key: value.trim()} : null;
  }
  function matches(url, method, status, id) {
    try {
      const u = new URL(url);
      return method === "GET" && status === 200 && /^[0-9]{6,20}$/.test(id) &&
        u.origin === "https://of.moncompteformation.gouv.fr" && !u.username && !u.password && !u.search && !u.hash &&
        u.pathname === `/edof-api/v1/api/private/siret/${SIRET}/organisms/current/registration-folders/${id}`;
    } catch { return false; }
  }
  function pick(object, keys) {
    const result = {};
    if (!object || typeof object !== "object" || Array.isArray(object)) return result;
    for (const key of keys) {
      const value = object[key];
      if (value === null || typeof value === "string" || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))) result[key] = value;
    }
    return result;
  }
  function sanitize(raw, id) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw) || raw.id !== id) throw new Error("Le numéro du dossier reçu ne correspond pas.");
    const folder = pick(raw, fields);
    folder.attendee = pick(raw.attendee, attendeeFields);
    folder.trainingActionInfo = pick(raw.trainingActionInfo, infoFields);
    return {siret: SIRET, folder};
  }
  return Object.freeze({ORIGIN, SIRET, parseKey, matches, sanitize});
})();
if (typeof module !== "undefined" && module.exports) module.exports = EdofTest;
