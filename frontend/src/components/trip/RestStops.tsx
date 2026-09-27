import { MapPinned, Navigation, Phone } from 'lucide-react'
import { HAZARD_LABELS, clock, directionsUrl, duration, type RestOption, type RestStop } from '../../lib/trip'
import { GoogleRating, KIND } from './stopKinds'


function Option({ option }: { option: RestOption }) {
  const { label, Icon } = KIND[option.kind]
  const details = [
    label,
    option.detour_km <= 0.3 ? 'on the route' : `${option.detour_km} km off the route`,
    option.opening_hours === '24/7' ? 'open 24 hours' : option.opening_hours ? `hours ${option.opening_hours}` : null,
    option.cuisine ? option.cuisine.replace(/;/g, ', ') : null,
    option.stars ? `${option.stars}★` : null,
  ].filter(Boolean)
  return (
    <li className={`rest-option ${option.kind}`}>
      <Icon size={15} />
      <span>
        <b>
          {option.name} <GoogleRating google={option.google} />
        </b>
        <small>{details.join(' · ')}</small>
      </span>
      <nav>
        {option.phone && (
          <a href={`tel:${option.phone.split(/[;,]/)[0].replace(/\s/g, '')}`} aria-label={`Call ${option.name}`}>
            <Phone size={13} />
          </a>
        )}
        <a href={directionsUrl(option.lat, option.lon)} target="_blank" rel="noreferrer" aria-label={`Directions to ${option.name}`}>
          <Navigation size={13} />
        </a>
        <a href={option.osm} target="_blank" rel="noreferrer" aria-label={`${option.name} on OpenStreetMap`}>
          <MapPinned size={13} />
        </a>
      </nav>
    </li>
  )
}

export default function RestStops({ stops, mode }: { stops: RestStop[]; mode: string }) {
  if (!stops.length) {
    return <p className="trip-clear">This trip is short enough to drive without a planned break.</p>
  }
  return (
    <ol className="rest-stops">
      {stops.map((stop, k) => (
        <li key={k} className={stop.reason}>
          <header>
            <em>{stop.reason === 'overnight' ? 'Overnight stay' : `Break ${k + 1}`}</em>
            <b>
              {stop.near ?? `km ${Math.round(stop.km)}`}
              <small>
                {' '}
                · after {duration(stop.after_min)} of {mode === 'bike' ? 'riding' : 'driving'} · km {Math.round(stop.km)}
                {!stop.after_overnight && ` · about ${clock(stop.eta)}`}
              </small>
            </b>
            {stop.weather && (
              <span className="rest-weather">
                {stop.weather.label}
                {stop.weather.temp !== null ? `, ${Math.round(stop.weather.temp)}°C` : ''}
              </span>
            )}
          </header>
          {stop.reason === 'overnight' && (
            <p className="rest-why">Driving through the night is the biggest risk on long road trips. Rest here and continue in daylight.</p>
          )}
          {stop.wait_out && (
            <p className="rest-wait">
              {HAZARD_LABELS[stop.wait_out.kind] ?? stop.wait_out.kind} ahead{stop.wait_out.near ? ` near ${stop.wait_out.near}` : ''}: {stop.wait_out.detail}. A good place to wait it out.
            </p>
          )}
          {stop.options.length > 0 ? (
            <ul>
              {stop.options.map((option) => (
                <Option key={option.osm} option={option} />
              ))}
            </ul>
          ) : (
            <p className="rest-none">{stop.error ?? 'No named places are mapped on OpenStreetMap near this stretch.'}</p>
          )}
          {stop.lodging_nearby && (
            <p className="rest-lodging">
              No hotels are mapped within 10 km here. Nearest stay on the route: <b>{stop.lodging_nearby.name}</b>
              {stop.lodging_nearby.near ? ` near ${stop.lodging_nearby.near}` : ''} (km {Math.round(stop.lodging_nearby.km)}).{' '}
              <a href={directionsUrl(stop.lodging_nearby.lat, stop.lodging_nearby.lon)} target="_blank" rel="noreferrer">
                Directions
              </a>
            </p>
          )}
        </li>
      ))}
    </ol>
  )
}
