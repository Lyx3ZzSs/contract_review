/* Shared conservative evidence policy; no editor or DOM dependency. */
globalThis.RixinEvidence = Object.freeze({
  validate(paragraph,quote,paragraphCount,quoteCount) {
    if(typeof paragraph!=='string'||typeof quote!=='string'||!quote||!paragraph.includes(quote)) return 'not_found';
    if(paragraphCount===0||quoteCount===0) return 'not_found';
    if(paragraphCount!==1||quoteCount!==1) return 'ambiguous';
    return 'located';
  }
});
