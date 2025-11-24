import React from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Treemap
} from 'recharts'
import { Download, BarChart3, PieChart as PieChartIcon, TreePine } from 'lucide-react'
import { formatBytes } from '@/lib/utils'

interface ChartsCardProps {
  data: Array<{
    name: string
    size: number
    rowCount: number
    indexSize: number
  }>
  title: string
  description: string
}

const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#06B6D4', '#84CC16', '#F97316']

export function ChartsCard({ data, title, description }: ChartsCardProps) {
  const [chartType, setChartType] = React.useState<'bar' | 'pie' | 'treemap'>('bar')

  const chartData = data.map((item, index) => ({
    ...item,
    sizeFormatted: formatBytes(item.size),
    color: COLORS[index % COLORS.length]
  }))

  const pieData = chartData.map(item => ({
    name: item.name,
    value: item.size,
    color: item.color
  }))

  const treemapData = chartData.map(item => ({
    name: item.name,
    size: item.size,
    color: item.color
  }))

  const exportChart = () => {
    // In a real implementation, this would export the chart as PNG/CSV
    console.log('Exporting chart...', { chartType, data: chartData })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center space-x-2">
              <BarChart3 className="h-5 w-5" />
              <span>{title}</span>
            </CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
          <div className="flex items-center space-x-2">
            <div className="flex rounded-lg border">
              <Button
                variant={chartType === 'bar' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setChartType('bar')}
              >
                <BarChart3 className="h-4 w-4" />
              </Button>
              <Button
                variant={chartType === 'pie' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setChartType('pie')}
              >
                <PieChartIcon className="h-4 w-4" />
              </Button>
              <Button
                variant={chartType === 'treemap' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setChartType('treemap')}
              >
                <TreePine className="h-4 w-4" />
              </Button>
            </div>
            <Button variant="outline" size="sm" onClick={exportChart}>
              <Download className="h-4 w-4 mr-2" />
              Export
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            {chartType === 'bar' && (
              <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis 
                  dataKey="name" 
                  angle={-45}
                  textAnchor="end"
                  height={80}
                  fontSize={12}
                />
                <YAxis 
                  tickFormatter={(value) => formatBytes(value)}
                  fontSize={12}
                />
                <Tooltip 
                  formatter={(value: number) => [formatBytes(value), 'Size']}
                  labelFormatter={(label) => `Table: ${label}`}
                />
                <Bar dataKey="size" fill="#3B82F6" />
              </BarChart>
            )}
            {chartType === 'pie' && (
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {pieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip formatter={(value: number) => [formatBytes(value), 'Size']} />
              </PieChart>
            )}
            {chartType === 'treemap' && (
              <Treemap
                data={treemapData}
                dataKey="size"
                aspectRatio={4/3}
                stroke="#fff"
                fill="#8884d8"
              >
                <Tooltip 
                  formatter={(value: number) => [formatBytes(value), 'Size']}
                  labelFormatter={(label) => `Table: ${label}`}
                />
              </Treemap>
            )}
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
