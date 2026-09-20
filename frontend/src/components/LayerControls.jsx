const labels = { active: 'Active fire', spread: 'Projected spread', recommended: 'Recommended route', alternative: 'Alternative route', fuel: 'Fuel', wind: 'Wind' }
export default function LayerControls({ layers, onChange }) {
  return <fieldset className="layers"><legend>Map layers</legend>{Object.entries(labels).map(([key, label]) => <label key={key}><input type="checkbox" checked={layers[key]} onChange={() => onChange(key)} />{label}</label>)}</fieldset>
}
