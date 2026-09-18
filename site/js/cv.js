/* Reading a CV, entirely in the browser.
 *
 * Nothing here touches the network with the file's contents: PDF and DOCX are
 * parsed client-side and the extracted text is kept in localStorage only.
 */
const CvReader = (() => {

  if (window.pdfjsLib) {
    window.pdfjsLib.GlobalWorkerOptions.workerSrc =
      'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  }

  const MAX_BYTES = 12 * 1024 * 1024;

  async function readPdf(file) {
    if (!window.pdfjsLib) throw new Error('PDF reader failed to load — try pasting your CV as text.');
    const buf = await file.arrayBuffer();
    const pdf = await window.pdfjsLib.getDocument({ data: buf }).promise;
    const pages = [];
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const content = await page.getTextContent();
      // Re-insert spacing: pdf.js hands back positioned fragments, not words.
      pages.push(content.items.map(item => item.str).join(' '));
    }
    return pages.join('\n');
  }

  async function readDocx(file) {
    if (!window.mammoth) throw new Error('Word reader failed to load — try saving as PDF.');
    const buf = await file.arrayBuffer();
    const result = await window.mammoth.extractRawText({ arrayBuffer: buf });
    return result.value || '';
  }

  function readText(file) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => resolve(String(fr.result || ''));
      fr.onerror = () => reject(new Error('Could not read that file.'));
      fr.readAsText(file);
    });
  }

  async function extract(file) {
    if (file.size > MAX_BYTES) throw new Error('That file is over 12 MB — is it definitely a CV?');
    const name = (file.name || '').toLowerCase();
    let text;
    if (name.endsWith('.pdf')) text = await readPdf(file);
    else if (name.endsWith('.docx')) text = await readDocx(file);
    else if (name.endsWith('.doc')) {
      throw new Error('Old .doc files aren\'t supported — save it as PDF or .docx first.');
    } else text = await readText(file);

    text = clean(text);
    if (text.replace(/\s/g, '').length < 120) {
      throw new Error('Barely any text came out. If your CV is a scan or image, paste the text instead.');
    }
    return text;
  }

  function clean(text) {
    return (text || '')
      .replace(/ /g, ' ')
      .replace(/[‘’]/g, "'")
      .replace(/[“”]/g, '"')
      .replace(/[ \t]+/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  return { extract, clean };
})();
