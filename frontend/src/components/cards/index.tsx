import type { Card } from '../../lib/types'
import AirCard from './AirCard'
import AlertsCard from './AlertsCard'
import AviationCard from './AviationCard'
import ClimateCard from './ClimateCard'
import ForecastCard from './ForecastCard'
import MarineCard from './MarineCard'
import ModelsCard from './ModelsCard'

export default function DataCard({ card }: { card: Card }) {
  switch (card.kind) {
    case 'forecast':
      return <ForecastCard place={card.place} data={card.data} />
    case 'alerts':
      return <AlertsCard place={card.place} data={card.data} />
    case 'climate':
      return <ClimateCard place={card.place} data={card.data} />
    case 'models':
      return <ModelsCard place={card.place} data={card.data} />
    case 'air':
      return <AirCard place={card.place} data={card.data} />
    case 'marine':
      return <MarineCard place={card.place} data={card.data} />
    case 'aviation':
      return <AviationCard data={card.data} />
  }
}
