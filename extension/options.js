const form = document.getElementById("add");
const input = document.getElementById("host");
const listEl = document.getElementById("list");
const empty = document.getElementById("empty");
const error = document.getElementById("error");

async function render() {
  const list = (await MprisIgnore.load()).sort();
  listEl.textContent = "";
  empty.hidden = list.length > 0;
  for (const entry of list) {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = entry;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", async () => {
      const current = await MprisIgnore.load();
      await MprisIgnore.save(current.filter(e => e !== entry));
      render();
    });
    item.append(name, remove);
    listEl.append(item);
  }
}

form.addEventListener("submit", async e => {
  e.preventDefault();
  const entry = MprisIgnore.normalize(input.value);
  if (!entry) {
    error.textContent = "Enter a site such as example.com";
    input.focus();
    return;
  }
  error.textContent = "";
  const list = await MprisIgnore.load();
  if (!list.includes(entry)) list.push(entry);
  await MprisIgnore.save(list);
  input.value = "";
  render();
});

render();
